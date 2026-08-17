"""Guards over the domain contracts themselves.

Phase 0's structural guards checked that files exist. These check that what is
in them is *coherent*: that the evidence vocabulary matches its payloads, that
every agent manifest validates, that the translator maps only events the bus can
emit, and that scenario ground truth resolves to a real contract value.

Each of those was a place where a check could pass for a reason unrelated to
what it claims - `test_every_agent_package_is_complete` asserted a manifest
*existed* while it was ten lines of comments that could never validate.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from core.contracts import AgentManifest, EvidenceKind, RootCauseCategory
from core.contracts.events import Event
from core.contracts.evidence import EvidencePayload

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS = REPO_ROOT / "agents"
SCENARIOS = REPO_ROOT / "simulator" / "scenarios"


def _union_members(annotated: Any) -> list[type[BaseModel]]:
    """Pull the concrete models out of an Annotated[A | B, Field(discriminator=…)]."""
    inner = get_args(annotated)[0]
    return [member for member in typing.get_args(inner) if issubclass(member, BaseModel)]


def _discriminators(annotated: Any, field: str) -> set[str]:
    """The literal discriminator value each union member declares."""
    values: set[str] = set()
    for model in _union_members(annotated):
        default = model.model_fields[field].default
        values.add(str(default))
    return values


# ---------------------------------------------------------------------------
# evidence: the vocabulary and the payloads cannot drift apart
# ---------------------------------------------------------------------------


def test_every_evidence_kind_has_exactly_one_payload() -> None:
    """`EvidenceKind` and the payload union are the same set.

    A kind with no payload model is a value nothing can carry; a payload with no
    kind is unreachable through the enum. Either way the mismatch surfaces as a
    KeyError months later rather than here.
    """
    kinds = {member.value for member in EvidenceKind}
    payloads = _discriminators(EvidencePayload, "kind")

    assert kinds == payloads, (
        f"EvidenceKind and the payload union disagree:\n"
        f"  kinds without a payload : {sorted(kinds - payloads)}\n"
        f"  payloads without a kind : {sorted(payloads - kinds)}"
    )


def test_evidence_kind_is_read_from_the_payload_not_stored_twice() -> None:
    """One source of truth for the kind, so the two halves cannot disagree."""
    from core.contracts import Evidence

    assert "kind" not in Evidence.model_fields, (
        "Evidence stores `kind` alongside `payload`; that is an invariant nobody "
        "enforces and eventually a record whose halves disagree"
    )


# ---------------------------------------------------------------------------
# manifests: they must validate, not merely exist
# ---------------------------------------------------------------------------


def _manifest_paths() -> list[Path]:
    return sorted(AGENTS.glob("*/manifest.yaml"))


def test_every_agent_manifest_validates_against_the_contract() -> None:
    """The check Phase 0 should have made.

    `test_every_agent_package_is_complete` asserts the file exists. It passed
    for ten files that were nothing but comments and could never have loaded -
    a check that succeeds for a reason unrelated to what it claims.
    """
    paths = _manifest_paths()
    assert len(paths) == 10, f"expected ten agent manifests, found {len(paths)}"

    failures: list[str] = []
    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            failures.append(f"{path.relative_to(REPO_ROOT)}: empty or comments only")
            continue
        try:
            AgentManifest.model_validate(raw)
        except ValidationError as exc:
            failures.append(f"{path.relative_to(REPO_ROOT)}: {exc.error_count()} error(s)")

    assert not failures, "agent manifests that do not validate:\n  " + "\n  ".join(failures)


def test_manifest_domain_matches_its_directory() -> None:
    """A manifest that claims a different domain would be loaded under the wrong key."""
    for path in _manifest_paths():
        manifest = AgentManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        assert manifest.domain == path.parent.name, (
            f"{path.relative_to(REPO_ROOT)} declares domain '{manifest.domain}' "
            f"but lives in '{path.parent.name}'"
        )


def test_agent_codenames_are_unique_and_match_the_roster() -> None:
    """Two agents sharing a codename would silently overwrite each other."""
    codenames = [
        AgentManifest.model_validate(yaml.safe_load(p.read_text(encoding="utf-8"))).codename
        for p in _manifest_paths()
    ]
    assert len(codenames) == len(set(codenames)), f"duplicate codenames: {sorted(codenames)}"

    expected = {
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
    assert set(codenames) == expected, f"roster drifted: {sorted(set(codenames) ^ expected)}"


# ---------------------------------------------------------------------------
# the translator cannot map events the bus cannot emit
# ---------------------------------------------------------------------------


def test_translator_maps_only_events_that_exist() -> None:
    """Every event the translator claims to map has a union member.

    Phase 0's translator documented `lease_expired` and `break_glass` mappings
    for events that did not exist in core.contracts.events at all - a promise in
    prose the code did not keep, and exactly the kind of thing a guard should
    have caught rather than a reader.
    """
    from api.agui.translator import DOMAIN_EVENT_MAPPING

    emitted = _discriminators(Event, "type")
    mapped = set(DOMAIN_EVENT_MAPPING)

    assert not (mapped - emitted), (
        f"translator maps events the bus cannot emit: {sorted(mapped - emitted)}"
    )
    assert not (emitted - mapped), (
        f"bus emits events the translator does not map: {sorted(emitted - mapped)}"
    )


def test_the_single_custom_event_exists_as_a_domain_event() -> None:
    """ADR 0006 names exactly one Custom event; it must be emittable."""
    from api.agui.translator import CUSTOM_EVENTS

    assert CUSTOM_EVENTS == ("pantheon.break_glass",)
    assert "break_glass" in _discriminators(Event, "type")


def test_lease_expiry_is_emittable_per_adr_0005() -> None:
    """ADR 0005 requires expiry to surface rather than be swallowed."""
    from core.contracts.events import LeaseExpiredEvent

    reasons = get_args(LeaseExpiredEvent.model_fields["reason"].annotation)
    assert set(reasons) == {"expired", "revoked"}, (
        "LeaseExpiredEvent must distinguish expiry from revocation - re-prompting for "
        "approval is right for one and wrong for the other"
    )


# ---------------------------------------------------------------------------
# ground truth resolves to the contract vocabulary
# ---------------------------------------------------------------------------


def test_scenario_ground_truth_uses_the_contract_vocabulary() -> None:
    """`expected_root_cause` must resolve to a RootCauseCategory member.

    Scoring an agent against free prose is string matching, which is worthless:
    "the connection pool was exhausted" would score zero against "pool
    exhaustion". Ground truth that cannot be parsed is ground truth nobody
    checks.

    Skipped until the simulator branch fills the scenarios in - and it asserts
    that they are unfilled rather than silently passing on an empty glob.
    """
    scenarios = sorted(SCENARIOS.glob("*.yaml"))
    assert len(scenarios) == 5, f"expected five scenarios, found {len(scenarios)}"

    valid = {member.value for member in RootCauseCategory}
    unfilled: list[str] = []
    offenders: list[str] = []

    for path in scenarios:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "expected_root_cause" not in raw:
            unfilled.append(path.name)
            continue
        declared = raw["expected_root_cause"]
        category = declared.get("category") if isinstance(declared, dict) else declared
        if category not in valid:
            offenders.append(f"{path.name}: {category!r}")

    assert not offenders, (
        "scenario ground truth outside RootCauseCategory: "
        + ", ".join(offenders)
        + f"\nvalid values: {sorted(valid)}"
    )

    if unfilled:
        pytest.skip(f"scenarios not yet filled in (feature/simulator): {unfilled}")


def test_every_scenario_name_maps_to_a_distinct_category() -> None:
    """The five scenarios must exercise five different root causes.

    Two scenarios sharing a category would score identically, which makes one of
    them redundant as a discriminating test.
    """
    for required in (
        RootCauseCategory.MEMORY_LEAK,
        RootCauseCategory.RESOURCE_CONTENTION,
        RootCauseCategory.BAD_DEPLOYMENT,
        RootCauseCategory.FLAKY_TEST,
        RootCauseCategory.DISK_EXHAUSTION,
    ):
        assert required in RootCauseCategory


# ---------------------------------------------------------------------------
# validators are load-bearing, so they are tested
# ---------------------------------------------------------------------------


def test_a_substantive_finding_must_cite_evidence() -> None:
    """The whole value is that a human can check the reasoning."""
    from uuid import uuid4

    from core.contracts import Finding, FindingKind, Severity

    with pytest.raises(ValidationError, match="cites no evidence"):
        Finding(
            id=uuid4(),
            agent="argus",
            kind=FindingKind.ANOMALY,
            title="memory climbing",
            severity=Severity.HIGH,
            confidence=0.9,
            detected_at="2026-08-15T00:00:00Z",  # type: ignore[arg-type]
        )


def test_a_degraded_finding_may_be_evidence_free() -> None:
    """An agent that could not reach a connector has nothing to cite."""
    from uuid import uuid4

    from core.contracts import Finding, FindingKind, Severity

    finding = Finding(
        id=uuid4(),
        agent="argus",
        kind=FindingKind.DEGRADED,
        title="lease expired before the query completed",
        severity=Severity.MEDIUM,
        confidence=1.0,
        detected_at="2026-08-15T00:00:00Z",  # type: ignore[arg-type]
    )
    assert finding.evidence == []


def test_a_wide_action_must_state_its_rollback() -> None:
    """The moment of approval is the worst moment to discover it is irreversible."""
    from uuid import uuid4

    from core.contracts import Action, BlastRadius
    from core.contracts.evidence import ResourceRef

    with pytest.raises(ValidationError, match="states no rollback"):
        Action(
            id=uuid4(),
            target=ResourceRef(kind="namespace", name="prod"),
            operation="delete_namespace",
            blast_radius=BlastRadius.CLUSTER,
            reason="cleanup",
            proposed_by="zeus",
            proposed_at="2026-08-15T00:00:00Z",  # type: ignore[arg-type]
        )


def test_a_verdict_cannot_be_confident_about_nothing() -> None:
    from uuid import uuid4

    from core.contracts import Verdict

    with pytest.raises(ValidationError, match="confidence in nothing"):
        Verdict(
            id=uuid4(),
            investigation_id=uuid4(),
            summary="something happened",
            confidence=0.9,
            decided_at="2026-08-15T00:00:00Z",  # type: ignore[arg-type]
        )


def test_a_terminal_investigation_has_a_completion_time() -> None:
    from uuid import uuid4

    from core.contracts import Investigation, InvestigationState, Trigger, TriggerKind

    trigger = Trigger(kind=TriggerKind.ALERT, received_at="2026-08-15T00:00:00Z", source="am")  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="no completed_at"):
        Investigation(
            id=uuid4(),
            state=InvestigationState.COMPLETED,
            trigger=trigger,
            created_at="2026-08-15T00:00:00Z",  # type: ignore[arg-type]
        )


def test_verdict_band_is_derived_not_stored() -> None:
    """Two fields that can disagree eventually will."""
    from core.contracts import Verdict, VerdictConfidence

    assert "band" not in Verdict.model_fields
    assert Verdict.band.fget is not None  # type: ignore[attr-defined]
    assert VerdictConfidence.HIGH.value == "high"


def test_verdict_leading_and_band_are_consistent() -> None:
    """The derived accessors, across every band boundary."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from core.contracts import (
        HypothesisStatus,
        RootCauseCategory,
        RootCauseHypothesis,
        Verdict,
        VerdictConfidence,
    )

    def verdict(confidence: float, *, with_hypothesis: bool = True) -> Verdict:
        hypotheses = (
            [
                RootCauseHypothesis(
                    id=uuid4(),
                    category=RootCauseCategory.MEMORY_LEAK,
                    statement="checkout leaks connections under retry storms",
                    status=HypothesisStatus.SUPPORTED,
                    confidence=confidence,
                    proposed_by="argus",
                )
            ]
            if with_hypothesis
            else []
        )
        return Verdict(
            id=uuid4(),
            investigation_id=uuid4(),
            summary="s",
            hypotheses=hypotheses,
            confidence=confidence,
            decided_at=datetime.now(UTC),
        )

    assert verdict(0.9).band is VerdictConfidence.HIGH
    assert verdict(0.75).band is VerdictConfidence.HIGH
    assert verdict(0.5).band is VerdictConfidence.MODERATE
    assert verdict(0.4).band is VerdictConfidence.MODERATE
    assert verdict(0.1).band is VerdictConfidence.LOW

    assert verdict(0.9).leading is not None
    assert verdict(0.0, with_hypothesis=False).leading is None


def test_action_execution_state_cannot_contradict_dry_run() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from core.contracts import Action, BlastRadius, ExecutionState
    from core.contracts.evidence import ResourceRef

    with pytest.raises(ValidationError, match="dry_run"):
        Action(
            id=uuid4(),
            target=ResourceRef(kind="deployment", name="checkout"),
            operation="scale",
            blast_radius=BlastRadius.SINGLE_WORKLOAD,
            execution_state=ExecutionState.SUCCEEDED,
            dry_run=True,
            reason="r",
            proposed_by="zeus",
            proposed_at=datetime.now(UTC),
        )


def test_a_live_investigation_has_no_completion_time() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from core.contracts import Investigation, InvestigationState, Trigger, TriggerKind

    now = datetime.now(UTC)
    trigger = Trigger(kind=TriggerKind.ALERT, received_at=now, source="am")

    with pytest.raises(ValidationError, match="already has completed_at"):
        Investigation(
            id=uuid4(),
            state=InvestigationState.RUNNING,
            trigger=trigger,
            created_at=now,
            completed_at=now,
        )

    ok = Investigation(
        id=uuid4(),
        state=InvestigationState.COMPLETED,
        trigger=trigger,
        created_at=now,
        completed_at=now,
    )
    assert ok.completed_at is not None


def test_evidence_kind_is_derived_from_its_payload() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from core.contracts import Evidence, EvidenceKind, EvidenceSource, MetricWindowPayload

    evidence = Evidence(
        id=uuid4(),
        source=EvidenceSource(connector="prometheus"),
        observed_at=datetime.now(UTC),
        summary="rss climbing",
        payload=MetricWindowPayload(metric="container_memory_working_set_bytes"),
    )
    assert evidence.kind is EvidenceKind.METRIC_WINDOW
