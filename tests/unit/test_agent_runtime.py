"""Guards over the agent runtime: registry, allowlist, budget and degradation.

BaseAgent is the shape ten agents repeat, so the properties that matter are the
ones a subclass cannot opt out of. Each guard below is aimed at the level where
the defect can exist: at the base class, not at any agent's good intentions.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from agents._base.base_agent import (
    AgentContext,
    AgentDegraded,
    AgentStatus,
    BaseAgent,
)
from agents._base.testing import CountingConnector, RecordingBus, UnreachableConnector, a_context
from agents._base.tool_binding import (
    BoundTools,
    ToolBudgetExceeded,
    ToolNotBound,
    ToolNotDeclared,
)
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.plan import PlanStep, StepStatus
from core.registry import capabilities as caps
from core.registry.loader import (
    ManifestError,
    for_codename,
    for_domain,
    load_all,
    load_manifest,
    manifest_paths,
)
from tests.mechanism import read_data

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "agents"

#: The roster, from the repository map. Ten domain agents; Zeus is not one.
EXPECTED_AGENTS = {
    "argus",
    "lethe",
    "hermes",
    "hephaestus",
    "aegis",
    "moira",
    "mnemosyne",
    "clio",
    "themis",
    "eris",
}


# --- the registry ------------------------------------------------------------


def test_every_manifest_on_disk_loads_through_the_real_loader() -> None:
    """Not `yaml.safe_load` in the test - the loader the runtime actually uses."""
    manifests = load_all()
    assert set(manifests) == EXPECTED_AGENTS, (
        f"roster on disk is {sorted(manifests)}, the map says {sorted(EXPECTED_AGENTS)}"
    )
    assert len(manifest_paths()) == len(EXPECTED_AGENTS)


def test_every_manifest_sits_in_the_folder_it_names() -> None:
    """The folder is how an agent finds its own manifest; they cannot disagree."""
    for path in manifest_paths():
        assert load_manifest(path).domain == path.parent.name


@pytest.mark.parametrize("codename", sorted(EXPECTED_AGENTS))
def test_every_agent_declares_at_least_one_capability(codename: str) -> None:
    """An agent with no capabilities can never be selected, so it is dead code."""
    assert load_all()[codename].capabilities, f"{codename} declares no capabilities"


# --- the loader fails loudly, which is the whole point of it -----------------


def _write(tmp: Path, name: str, body: str) -> Path:
    folder = tmp / name
    folder.mkdir()
    path = folder / "manifest.yaml"
    path.write_text(body, encoding="utf-8")
    return path


#: A manifest that satisfies the contract, for mutating one field at a time.
VALID_MANIFEST = chr(10).join(
    (
        "codename: argus",
        "domain: anomaly",
        "description: d",
        "capabilities: [{name: c, description: d}]",
        "tools: []",
        "budget: {max_tokens: 1, max_seconds: 1, max_tool_calls: 1}",
    )
)


def test_unparseable_yaml_names_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "anomaly", "codename: [unclosed")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(path)


def test_a_manifest_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    """A YAML list is valid YAML and not a manifest; the error says which."""
    path = _write(tmp_path, "anomaly", "[just, a, list]")
    with pytest.raises(ManifestError, match="expected a mapping"):
        load_manifest(path)


def test_a_manifest_that_fails_the_contract_keeps_pydantics_message(tmp_path: Path) -> None:
    """The field path pydantic reports is the fastest way to fix it."""
    path = _write(tmp_path, "anomaly", "codename: argus")
    with pytest.raises(ManifestError, match="does not satisfy AgentManifest"):
        load_manifest(path)


def test_a_manifest_whose_domain_disagrees_with_its_folder_is_refused(tmp_path: Path) -> None:
    """The folder is how the runtime finds it, so they cannot disagree."""
    body = VALID_MANIFEST.replace("domain: anomaly", "domain: elsewhere")
    with pytest.raises(ManifestError, match="lives in"):
        load_manifest(_write(tmp_path, "anomaly", body))


def test_a_valid_manifest_in_the_right_folder_loads(tmp_path: Path) -> None:
    """The control: the fixture above is only evidence if this one passes."""
    assert load_manifest(_write(tmp_path, "anomaly", VALID_MANIFEST)).codename == "argus"


def test_an_unknown_codename_lists_the_ones_that_exist() -> None:
    with pytest.raises(ManifestError, match="argus"):
        for_codename("aargus")


def test_an_unknown_domain_lists_the_ones_that_exist() -> None:
    with pytest.raises(ManifestError, match="anomaly"):
        for_domain("anomally")


def test_manifest_paths_skips_scaffolding(tmp_path: Path) -> None:
    """`_base` is scaffolding, not an agent; the underscore is load-bearing."""
    _write(tmp_path, "anomaly", VALID_MANIFEST)
    _write(tmp_path, "_base", VALID_MANIFEST)
    assert [path.parent.name for path in manifest_paths(tmp_path)] == ["anomaly"]


# --- capability matching -----------------------------------------------------


def test_capability_matching_resolves_to_the_agent_that_declares_it() -> None:
    """Zeus plans by capability, so the mapping has to be exact and total."""
    assert caps.declares("argus", "detect_metric_anomaly")
    assert not caps.declares("argus", "cluster_logs")

    matched = caps.agents_for("detect_metric_anomaly")
    assert [m.codename for m in matched] == ["argus"]
    assert caps.best_for("detect_metric_anomaly").codename == "argus"


def test_every_declared_capability_is_reachable_from_the_index() -> None:
    """Both directions: the index and the manifests describe the same set."""
    index = caps.capabilities()
    for manifest in load_all().values():
        for capability in manifest.capabilities:
            assert manifest.codename in index[capability.name]


def test_an_unknown_capability_names_the_ones_that_exist() -> None:
    """A silent empty list would make a planning bug look like an empty roster."""
    with pytest.raises(caps.NoCapableAgent, match="detect_metric_anomaly"):
        caps.agents_for("detect_metric_anomally")


# --- the manifest is an allowlist -------------------------------------------


class _Probe(BaseAgent):
    """A minimal agent, for exercising the base rather than any domain logic."""

    domain = "anomaly"

    def __init__(
        self,
        behaviour: Callable[[AgentContext], Awaitable[list[Finding]]],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._behaviour = behaviour

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return await self._behaviour(ctx)


def _an_observation(title: str = "something moved") -> Finding:
    from uuid import uuid4

    from core.contracts.evidence import (
        Evidence,
        EvidenceSource,
        MetricSample,
        MetricWindowPayload,
    )

    return Finding(
        id=uuid4(),
        agent="",
        kind=FindingKind.OBSERVATION,
        title=title,
        severity=Severity.LOW,
        confidence=0.8,
        detected_at=a_context().window_end,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="prometheus", query="pantheon_pod_cpu_cores"),
                observed_at=a_context().window_end,
                summary="checkout cpu 4.2 sigma above baseline",
                payload=MetricWindowPayload(
                    metric="pantheon_pod_cpu_cores",
                    samples=[MetricSample(at=a_context().window_end, value=1.0)],
                    deviation_sigma=4.2,
                ),
            )
        ],
    )


async def test_a_tool_the_manifest_does_not_declare_is_refused() -> None:
    """The manifest is the allowlist. Argus may not reach Loki."""
    tools = BoundTools(declared=frozenset({"prometheus.query_range"}), max_calls=5)
    tools.register("prometheus.query_range", CountingConnector())

    # ToolNotDeclared specifically, not "some error". Removing the allowlist
    # check used to leave this passing, because the unbound branch raised the
    # same type - a guard firing for the wrong reason is one refactor from
    # firing for none.
    with pytest.raises(ToolNotDeclared, match=r"loki\.query"):
        await tools.call("loki.query")

    tools_without_connector = BoundTools(declared=frozenset({"loki.query"}), max_calls=5)
    with pytest.raises(ToolNotBound, match=r"not running"):
        await tools_without_connector.call("loki.query")


async def test_an_undeclared_tool_cannot_even_be_bound() -> None:
    """Registration is the other half; binding it would make the call check moot."""
    tools = BoundTools(declared=frozenset({"prometheus.query_range"}), max_calls=5)
    with pytest.raises(ToolNotDeclared, match=r"loki\.query"):
        tools.register("loki.query", CountingConnector())


async def test_the_tool_call_budget_is_enforced_and_not_retryable() -> None:
    """`max_tool_calls` is a bound only if something counts."""
    tools = BoundTools(declared=frozenset({"prometheus.query_range"}), max_calls=2)
    tools.register("prometheus.query_range", CountingConnector())

    await tools.call("prometheus.query_range")
    await tools.call("prometheus.query_range")
    assert tools.calls_remaining == 0
    with pytest.raises(ToolBudgetExceeded, match="same wall"):
        await tools.call("prometheus.query_range")


# --- degradation is the runtime's job ---------------------------------------


async def test_an_agent_that_raises_produces_a_degraded_finding() -> None:
    """Any exception, not just a declared one. run() must never propagate."""

    async def explode(_ctx: AgentContext) -> list[Finding]:
        raise ConnectionError("prometheus refused the connection")

    outcome = await _Probe(explode).run(a_context())

    assert outcome.status is AgentStatus.DEGRADED
    assert [f.kind for f in outcome.findings] == [FindingKind.DEGRADED]
    assert "prometheus refused" in (outcome.degraded_reason or "")
    assert outcome.findings[0].agent == "argus"


async def test_a_degraded_finding_needs_no_evidence() -> None:
    """The contract exempts DEGRADED because it reports the absence of data."""

    async def explode(_ctx: AgentContext) -> list[Finding]:
        raise AgentDegraded("connector down", subject="prometheus")

    outcome = await _Probe(explode).run(a_context())
    assert outcome.findings[0].evidence == []


async def test_partial_results_survive_a_declared_degradation() -> None:
    """Three of four pods reachable is worth reporting, alongside the failure."""

    async def partial(_ctx: AgentContext) -> list[Finding]:
        raise AgentDegraded("1 of 4 pods unreachable", partial=[_an_observation()])

    outcome = await _Probe(partial).run(a_context())
    kinds = [f.kind for f in outcome.findings]
    assert kinds == [FindingKind.OBSERVATION, FindingKind.DEGRADED]


async def test_finding_nothing_is_complete_not_degraded() -> None:
    """A clean window is a result. Collapsing it into DEGRADED would be a lie."""

    async def clean(_ctx: AgentContext) -> list[Finding]:
        return []

    outcome = await _Probe(clean).run(a_context())
    assert outcome.status is AgentStatus.COMPLETE
    assert outcome.findings == []
    assert outcome.complete


async def test_the_seconds_budget_degrades_rather_than_hangs() -> None:
    """A wedged connector must not hold an investigation open forever."""

    async def forever(_ctx: AgentContext) -> list[Finding]:
        await asyncio.sleep(3600)
        return []

    probe = _Probe(forever)
    probe.manifest = probe.manifest.model_copy(
        update={"budget": probe.manifest.budget.model_copy(update={"max_seconds": 1})}
    )
    outcome = await probe.run(a_context())

    assert outcome.status is AgentStatus.DEGRADED
    assert "budget" in (outcome.degraded_reason or "")
    assert not outcome.retryable, "a timeout will time out again; retrying burns attempts"


def test_only_the_base_constructs_a_degraded_finding() -> None:
    """The guard that makes 'the runtime owns DEGRADED' a mechanism.

    Aimed at the level where the defect can exist: any agent module could build
    one, and ten authors remembering not to is not a property.
    """
    offenders: list[str] = []
    for path in sorted(AGENTS_DIR.rglob("*.py")):
        if "_base" in path.parts or "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(read_data(path))):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "DEGRADED"
                and isinstance(node.value, ast.Name)
                and node.value.id == "FindingKind"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert not offenders, (
        "agents constructing DEGRADED themselves: "
        + ", ".join(offenders)
        + ". Raise AgentDegraded and let the runtime build it, so every agent "
        "reports inability the same way."
    )


# --- deterministic identity --------------------------------------------------


async def test_the_same_claim_gets_the_same_id_on_every_attempt() -> None:
    """Retry safety as mechanism, not as a docstring asking for idempotency."""

    async def one(_ctx: AgentContext) -> list[Finding]:
        return [_an_observation()]

    ctx = a_context()
    first = await _Probe(one).run(ctx)
    second = await _Probe(one).run(ctx)

    assert first.findings[0].id == second.findings[0].id, (
        "a retry produced a different id for the same claim, so a consumer that "
        "upserts would duplicate it"
    )


async def test_a_different_claim_gets_a_different_id() -> None:
    """Dedup must collapse identical claims only, never distinct ones."""

    async def a(_ctx: AgentContext) -> list[Finding]:
        return [_an_observation("cpu high")]

    async def b(_ctx: AgentContext) -> list[Finding]:
        return [_an_observation("memory high")]

    ctx = a_context()
    assert (await _Probe(a).run(ctx)).findings[0].id != (await _Probe(b).run(ctx)).findings[0].id


async def test_detected_at_is_not_part_of_the_identity() -> None:
    """It is wall clock; including it would give every retry a fresh id."""
    from datetime import UTC, datetime, timedelta

    async def one(_ctx: AgentContext) -> list[Finding]:
        finding = _an_observation()
        return [finding.model_copy(update={"detected_at": datetime.now(UTC) + timedelta(hours=1)})]

    async def two(_ctx: AgentContext) -> list[Finding]:
        return [_an_observation()]

    ctx = a_context()
    assert (await _Probe(one).run(ctx)).findings[0].id == (await _Probe(two).run(ctx)).findings[
        0
    ].id


async def test_an_agent_cannot_speak_for_another_agent() -> None:
    """Attribution is how findings are scored; impersonation corrupts that."""

    async def impersonate(_ctx: AgentContext) -> list[Finding]:
        return [_an_observation().model_copy(update={"agent": "lethe"})]

    outcome = await _Probe(impersonate).run(a_context())

    # Rejected, and the rejection degrades rather than escaping. run() promises
    # never to raise, and stamping validates - so stamping has to be inside the
    # promise. It was not, until this test failed.
    assert outcome.status is AgentStatus.DEGRADED
    assert "only speak for itself" in (outcome.degraded_reason or "")
    assert [f.kind for f in outcome.findings] == [FindingKind.DEGRADED]
    assert not outcome.retryable, "the agent will return the same bad Finding again"


async def test_findings_are_published_on_the_bus() -> None:
    async def one(_ctx: AgentContext) -> list[Finding]:
        return [_an_observation()]

    bus = RecordingBus()
    outcome = await _Probe(one, bus=bus).run(a_context())
    published = bus.of_type("finding_produced")
    assert [event.finding.id for event in published] == [outcome.findings[0].id]


async def test_an_unreachable_connector_degrades_rather_than_crashes() -> None:
    """The fake that fails is the one worth having."""
    connector = UnreachableConnector()

    async def query(ctx: AgentContext) -> list[Finding]:
        await ctx.tools.call("prometheus.query_range", query="up")
        return []

    probe = _Probe(query)
    probe.bind_tools = lambda tools: tools.register(  # type: ignore[method-assign]
        "prometheus.query_range", connector
    )
    outcome = await probe.run(a_context())

    assert outcome.status is AgentStatus.DEGRADED
    assert connector.attempts == 1
    assert outcome.tool_calls == 1, "a failed call still spends budget"


# --- a finding list is not a record of execution -----------------------------


def test_a_verdict_cannot_be_formed_without_the_execution_record() -> None:
    """Structural closure of "findings alone cannot tell clean from never-ran"."""
    from core.contracts.verdict import Verdict

    assert Verdict.model_fields["steps"].is_required(), (
        "Verdict.steps must stay required. Defaulted, a verdict could be formed "
        "from findings alone, and a never-dispatched agent would be "
        "indistinguishable from a clean one."
    )


def test_partial_is_derived_from_what_ran_not_asserted() -> None:
    """It was a free boolean, so a verdict could claim completeness while degraded."""
    from uuid import uuid4

    from core.contracts.verdict import Verdict

    def verdict(*statuses: StepStatus) -> Verdict:
        return Verdict(
            id=uuid4(),
            investigation_id=uuid4(),
            summary="s",
            confidence=0.0,
            decided_at=a_context().window_end,
            steps=[
                PlanStep(agent=f"a{index}", reason="r", status=status)
                for index, status in enumerate(statuses)
            ],
        )

    assert not verdict(StepStatus.COMPLETE, StepStatus.COMPLETE).partial
    assert verdict(StepStatus.COMPLETE, StepStatus.DEGRADED).partial
    assert verdict(StepStatus.COMPLETE, StepStatus.SKIPPED).partial
    assert verdict(StepStatus.COMPLETE, StepStatus.DEGRADED).degraded_agents == ["a1"]


def test_nothing_reads_the_token_budget_yet() -> None:
    """`max_tokens` is carried but unenforced, and must not be half-wired.

    Nothing consumes tokens until Delphi lands, so there is no meter to enforce
    against. Writing an enforcement path that cannot be tested is the
    unfailable-guard class. This asserts the field stays untouched, so connecting
    it at Phase 2 is a conscious act rather than a half-finished one.
    """
    readers: list[str] = []
    for directory in ("core", "agents", "api", "simulator"):
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            for node in ast.walk(ast.parse(read_data(path))):
                if isinstance(node, ast.Attribute) and node.attr == "max_tokens":
                    readers.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert not readers, (
        "max_tokens is read at " + ", ".join(readers) + ". It is carried but not "
        "enforced until Delphi provides a meter (see ROADMAP). Wiring it means "
        "wiring it deliberately, with a test that can fail."
    )
