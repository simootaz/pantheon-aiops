"""Hephaestus: what a flake is, and what it refuses to call one.

The tests that matter are the refusals. A triage agent that labelled every
first failure would be right about half of them and trusted for neither, so the
central property is that one observation yields UNKNOWN.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from typing import Any

import pytest

from agents._base.base_agent import AgentStatus
from agents._base.testing import a_context
from agents.ci_triage.agent import MAX_RUNS, Hephaestus
from agents.ci_triage.tools import IMPLEMENTATIONS
from agents.ci_triage.triage import JobOutcome, Verdict, classify, outcomes_from

REPO = "acme/checkout"
SHA = "abc1234def"


def _outcome(name: str, conclusion: str, run_id: int = 1) -> JobOutcome:
    return JobOutcome(name=name, conclusion=conclusion, run_id=run_id)


# --- a flake has a definition -----------------------------------------------------------


def test_the_same_job_passing_and_failing_at_one_commit_is_a_flake() -> None:
    """Non-determinism by definition: the same job on the same input finishing
    two different ways. Not an inference from it."""
    (triage,) = classify([_outcome("test", "failure", 1), _outcome("test", "success", 2)])

    assert triage.verdict is Verdict.FLAKE
    assert "by definition" in triage.why


def test_a_job_that_only_ever_failed_is_unknown() -> None:
    """Most CI failures. Nothing distinguishes a flake nobody has re-run from a
    regression the change introduced, and labelling it would be a guess."""
    (triage,) = classify([_outcome("test", "failure", 1), _outcome("test", "failure", 2)])

    assert triage.verdict is Verdict.UNKNOWN
    assert "Re-running it" in triage.why


def test_one_observation_is_unknown_rather_than_a_regression() -> None:
    """A `REGRESSION` verdict would need the parent commit's runs, and the
    commits API is not reachable. Anything less would be UNKNOWN wearing a
    stronger word."""
    (triage,) = classify([_outcome("test", "failure")])

    assert triage.verdict is Verdict.UNKNOWN


def test_a_job_that_only_passed_is_not_reported() -> None:
    """A triage listing every green job is a triage nobody reads to the end."""
    assert classify([_outcome("test", "success")]) == []


def test_a_cancelled_job_is_not_a_failure() -> None:
    """A cancelled job says somebody pushed again. Counting it as a failure
    would make every force-push look like a broken test."""
    assert classify([_outcome("test", "cancelled")]) == []
    assert classify([_outcome("test", "skipped")]) == []


def test_a_timeout_is_a_failure() -> None:
    """The control. Treating only `failure` as a failure would let every
    hanging job pass triage silently."""
    (triage,) = classify([_outcome("test", "timed_out")])

    assert triage.verdict is Verdict.UNKNOWN


def test_a_cancelled_attempt_does_not_make_a_failure_flaky() -> None:
    """Cancelled is not a pass. If it counted as one, every failure somebody
    interrupted would be labelled non-deterministic."""
    (triage,) = classify([_outcome("test", "failure", 1), _outcome("test", "cancelled", 2)])

    assert triage.verdict is Verdict.UNKNOWN


def test_jobs_are_triaged_independently() -> None:
    """One flaky job does not make the whole run flaky, and one hard failure
    does not hide a flake beside it."""
    triaged = classify(
        [
            _outcome("unit", "failure", 1),
            _outcome("unit", "success", 2),
            _outcome("lint", "failure", 1),
            _outcome("lint", "failure", 2),
        ]
    )

    assert [(t.job, t.verdict) for t in triaged] == [
        ("lint", Verdict.UNKNOWN),
        ("unit", Verdict.FLAKE),
    ]


def test_the_order_of_the_report_does_not_depend_on_arrival() -> None:
    """Job results arrive in whichever order the runs were listed."""
    forwards = classify([_outcome("b", "failure"), _outcome("a", "failure")])
    backwards = classify([_outcome("a", "failure"), _outcome("b", "failure")])

    assert [t.job for t in forwards] == [t.job for t in backwards] == ["a", "b"]


# --- flattening GitHub's shapes ------------------------------------------------------------


def test_a_job_still_running_is_dropped_rather_than_counted_as_failed() -> None:
    """Treating an absent conclusion as a failure would make every in-progress
    pipeline look broken."""
    flattened = outcomes_from(
        [{"id": 1}],
        {1: [{"name": "test", "conclusion": None}, {"name": "lint", "conclusion": "failure"}]},
    )

    assert [outcome.name for outcome in flattened] == ["lint"]


def test_a_run_with_no_jobs_contributes_nothing() -> None:
    assert outcomes_from([{"id": 1}], {}) == []


# --- the agent -------------------------------------------------------------------------------


class _Forge:
    """A scripted GitHub Actions. Records what was asked for."""

    def __init__(
        self,
        runs: list[dict[str, Any]] | None = None,
        jobs: dict[int, list[dict[str, Any]]] | None = None,
        head_sha: str = SHA,
    ) -> None:
        self.runs = runs if runs is not None else [{"id": 1}]
        self.jobs = jobs or {}
        self.head_sha = head_sha
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def actions_run(self, **kwargs: Any) -> Any:
        self.calls.append(("actions_run", kwargs))
        return {"id": kwargs["run"], "head_sha": self.head_sha}

    async def workflow_runs(self, **kwargs: Any) -> Any:
        self.calls.append(("workflow_runs", kwargs))
        return {"workflow_runs": self.runs}

    async def jobs_for(self, **kwargs: Any) -> Any:
        self.calls.append(("jobs", kwargs))
        return {"jobs": self.jobs.get(int(kwargs["run"]), [])}

    def named(self, tool: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == tool]


async def _triage(forge: _Forge, params: dict[str, Any] | None = None) -> Any:
    from agents._base.tool_binding import BoundTools

    agent = Hephaestus()

    def _bind(tools: BoundTools) -> None:
        tools.register("github.actions_run", forge.actions_run)
        tools.register("github.workflow_runs", forge.workflow_runs)
        tools.register("github.jobs", forge.jobs_for)

    agent.bind_tools = _bind  # type: ignore[method-assign]
    ctx = a_context()
    ctx.params = params if params is not None else {"repository": REPO, "run": 1}
    return await agent.run(ctx)


@pytest.mark.asyncio
async def test_every_run_at_the_commit_is_read_not_just_the_one_that_fired() -> None:
    """The run that triggered this is one attempt. Reading only it makes every
    flake look like a plain failure - the agent would be structurally incapable
    of its one real capability."""
    forge = _Forge(
        runs=[{"id": 1}, {"id": 2}],
        jobs={
            1: [{"name": "unit", "conclusion": "failure"}],
            2: [{"name": "unit", "conclusion": "success"}],
        },
    )

    outcome = await _triage(forge)

    assert [call["head_sha"] for call in forge.named("workflow_runs")] == [SHA]
    assert sorted(call["run"] for call in forge.named("jobs")) == [1, 2]
    (finding,) = outcome.findings
    assert "is flaky" in finding.title
    assert finding.confidence == 1.0


@pytest.mark.asyncio
async def test_a_failure_with_no_rerun_is_reported_as_unexplained() -> None:
    """And at lower confidence. A confident "I do not know" would be a strange
    thing to assert at full strength."""
    forge = _Forge(runs=[{"id": 1}], jobs={1: [{"name": "unit", "conclusion": "failure"}]})

    outcome = await _triage(forge)

    (finding,) = outcome.findings
    assert "nothing here says why" in finding.title
    assert finding.confidence == 0.5
    assert "unknown" in finding.tags


@pytest.mark.asyncio
async def test_a_green_run_produces_no_findings() -> None:
    """A result, not a failure."""
    forge = _Forge(runs=[{"id": 1}], jobs={1: [{"name": "unit", "conclusion": "success"}]})

    outcome = await _triage(forge)

    assert outcome.status is AgentStatus.COMPLETE
    assert outcome.findings == []


@pytest.mark.asyncio
async def test_a_run_with_no_head_sha_degrades() -> None:
    """Without it the reruns cannot be found, and every flake reads as a plain
    failure. Reporting that as a clean triage would be worse than refusing."""
    forge = _Forge(head_sha="")

    outcome = await _triage(forge)

    assert outcome.status is AgentStatus.DEGRADED
    assert outcome.degraded_reason is not None
    assert "reruns cannot be found" in outcome.degraded_reason


@pytest.mark.asyncio
async def test_no_run_named_at_all_degrades() -> None:
    outcome = await _triage(_Forge(), params={})

    assert outcome.status is AgentStatus.DEGRADED
    assert outcome.degraded_reason is not None
    assert "not an empty result" in outcome.degraded_reason


@pytest.mark.asyncio
async def test_the_number_of_runs_read_is_bounded() -> None:
    """A quota bound, not a detection threshold: it changes how much is looked
    at and never what is concluded."""
    forge = _Forge(runs=[{"id": index} for index in range(MAX_RUNS + 5)])

    await _triage(forge)

    assert len(forge.named("jobs")) == MAX_RUNS


# --- the toolset ------------------------------------------------------------------------------


def test_every_declared_tool_has_an_implementation_and_no_others() -> None:
    """Asserted in both directions, so a tool added to either side alone
    fails."""
    assert set(Hephaestus().manifest.tools) == set(IMPLEMENTATIONS)


def test_gitlab_is_not_declared() -> None:
    """This deployment uses GitHub. A declared tool nobody calls makes an
    agent's reach unreadable from the one place it should be readable."""
    assert not [tool for tool in Hephaestus().manifest.tools if tool.startswith("gitlab.")]


def test_the_diff_is_not_declared_because_the_capability_is_not_built() -> None:
    """Linking a failure to the change that caused it needs the parent commit's
    runs, and the commits API is not reachable. A tool declared for a capability
    that is explicitly not built says the capability exists."""
    tools = Hephaestus().manifest.tools
    capabilities = {capability.name for capability in Hephaestus().manifest.capabilities}

    assert "github.diff" not in tools
    assert "correlate_with_change" not in capabilities


@pytest.mark.asyncio
async def test_every_declared_adapter_reaches_the_connector(monkeypatch: Any) -> None:
    """Through `attach` and the real adapters, with only the transport faked.

    The scripted forge above registers handlers directly, which skips the
    adapters - so one passing `sha=` where the connector expects `head_sha=`
    would be invisible.
    """
    import httpx

    from agents._base.tool_binding import BoundTools
    from agents.ci_triage.tools import attach

    seen: list[str] = []
    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> Any:
        def _answer(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"workflow_runs": []})

        kwargs["transport"] = httpx.MockTransport(_answer)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    tools = BoundTools(declared=frozenset(IMPLEMENTATIONS), max_calls=10)
    attach(tools)

    await tools.call("github.actions_run", repository=REPO, run=7)
    await tools.call("github.workflow_runs", repository=REPO, head_sha=SHA)
    await tools.call("github.jobs", repository=REPO, run=7)

    assert [url.split(REPO)[1].split("?")[0] for url in seen] == [
        "/actions/runs/7",
        "/actions/runs",
        "/actions/runs/7/jobs",
    ]
    assert f"head_sha={SHA}" in seen[1], "the commit filter is the whole of flake detection"


@pytest.mark.asyncio
async def test_bind_tools_attaches_the_real_implementations(monkeypatch: Any) -> None:
    """The tests above replace `bind_tools`, so the real one was never called -
    and one that attached nothing would leave every tool unbound at dispatch,
    which reads as "the connector is not running" rather than as a wiring bug.

    Asserted by CALLING each tool rather than by reading a private field: an
    unbound name raises `ToolNotBound`, so a successful call is the claim.
    """
    import httpx

    from agents._base.tool_binding import BoundTools

    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> Any:
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"workflow_runs": []})
        )
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    tools = BoundTools(declared=frozenset(IMPLEMENTATIONS), max_calls=5)
    Hephaestus().bind_tools(tools)

    await tools.call("github.actions_run", repository=REPO, run=7)
    await tools.call("github.workflow_runs", repository=REPO, head_sha=SHA)
    await tools.call("github.jobs", repository=REPO, run=7)


@pytest.mark.asyncio
async def test_a_run_with_a_malformed_id_is_skipped_rather_than_fatal() -> None:
    """GitHub's shapes are read defensively because a triage that crashed on one
    odd entry would lose the whole report - and the entries come over a wire."""
    forge = _Forge(
        runs=[{"id": "not-a-number"}, {"id": 2}],
        jobs={2: [{"name": "unit", "conclusion": "failure"}]},
    )

    outcome = await _triage(forge)

    assert [call["run"] for call in forge.named("jobs")] == [2]
    assert len(outcome.findings) == 1


@pytest.mark.asyncio
async def test_an_already_unwrapped_answer_is_accepted() -> None:
    """GitHub wraps runs in `workflow_runs` and jobs in `jobs`. A caller handing
    back a bare list - a cache, a replay, a different client - must not be a
    crash, because the wrapping is transport and the content is the same."""
    forge = _Forge()

    async def _bare_runs(**kwargs: Any) -> Any:
        forge.calls.append(("workflow_runs", kwargs))
        return [{"id": 1}]

    async def _bare_jobs(**kwargs: Any) -> Any:
        forge.calls.append(("jobs", kwargs))
        return [{"name": "unit", "conclusion": "failure"}]

    forge.workflow_runs = _bare_runs  # type: ignore[method-assign]
    forge.jobs_for = _bare_jobs  # type: ignore[method-assign]

    outcome = await _triage(forge)

    assert len(outcome.findings) == 1


def test_a_run_with_no_usable_id_contributes_no_outcomes() -> None:
    assert outcomes_from([{"id": None}], {1: [{"name": "unit", "conclusion": "failure"}]}) == []
