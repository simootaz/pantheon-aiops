"""The first write tool, and everything standing between it and an agent.

`policy.py` and `approval_gate.py` guarded a path that did not exist until now:
no connector had a write tool, so the guardrails were correct and unreachable.
`alertmanager.create_silence` is the first, and these are the checks that decide
whether it ever runs.

The structural guard at the top is the important one. Every check below it is
about the executor refusing correctly; that one is about an agent never getting
the chance to ask.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from connectors._base.python.base_server import ToolError
from connectors.alertmanager.tools import MAX_SILENCE_HOURS, build_server, create_silence
from core.config import Environment
from core.contracts.action import Action, BlastRadius, ExecutionState
from core.contracts.evidence import ResourceRef
from core.guardrails.approval_gate import ApprovalGate
from core.guardrails.executor import NotPermitted, execute
from core.guardrails.policy import Decision, evaluate
from core.registry import loader

MATCHERS = [{"name": "alertname", "value": "CheckoutErrorRateHigh", "isRegex": False}]


def _action(
    *,
    blast_radius: BlastRadius = BlastRadius.SINGLE_WORKLOAD,
    dry_run: bool = False,
) -> Action:
    return Action(
        id=uuid4(),
        target=ResourceRef(kind="alert", name="CheckoutErrorRateHigh"),
        operation="create_silence",
        parameters={"matchers": MATCHERS, "hours": 1, "created_by": "zeus", "comment": "why"},
        blast_radius=blast_radius,
        dry_run=dry_run,
        reason="the verdict says this alert is a known symptom",
        rollback="expire the silence",
        proposed_by="zeus",
        proposed_at=datetime.now(tz=UTC),
    )


class _Performer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def __call__(self, operation: str, parameters: dict[str, Any]) -> Any:
        self.calls.append((operation, parameters))
        if self.fail:
            raise ToolError("alertmanager returned 500")
        return {"silenceID": "abc"}


# --- the structural guard: an agent cannot even ask ---------------------------------


def test_no_agent_declares_a_mutating_tool() -> None:
    """Replaces `test_no_connector_exposes_a_mutating_tool`, retired 2026-08-30.

    That guard said: *"the moment a mutating tool exists it needs the approval
    path at Phase 3, and proving none exists is cheaper than discovering one
    that skipped it."* The approval path now exists and so does the tool, so its
    condition is met and it is gone rather than left asserting something no
    longer true.

    This is what replaces it, and it is the stronger claim. An agent that cannot
    reach a write tool is safe by construction; an agent trusted not to call one
    is safe by convention. The manifest is the allowlist, so a mutating tool
    declared in one is a capability handed over - and that must fail here.
    """
    mutating = {
        tool.name for build in (build_server,) for tool in build().tools.values() if tool.mutating
    }
    assert mutating, "no mutating tool exists, so this guard has no subject"

    offenders = {
        manifest.codename: sorted(set(manifest.tools) & mutating)
        for manifest in loader.load_all().values()
        if set(manifest.tools) & mutating
    }
    assert not offenders, (
        f"agents declare mutating tools: {offenders}. A manifest is an allowlist, "
        "so declaring one hands the agent a capability core/guardrails/executor.py "
        "exists to withhold."
    )


def test_the_write_tool_declares_that_it_writes() -> None:
    """The field, not a verb in the name. The guard above reads THIS to decide
    what an agent may not declare, so a tool that writes and forgets the flag is
    reachable from an agent."""
    tool = build_server().tools["alertmanager.create_silence"]

    assert tool.mutating is True
    assert build_server().read_only is False


def test_the_read_tools_still_declare_that_they_do_not() -> None:
    """The control. A connector where everything is mutating would pass the test
    above and make the structural guard forbid every tool."""
    server = build_server()

    assert server.tools["alertmanager.list_alerts"].mutating is False
    assert server.tools["alertmanager.list_silences"].mutating is False


# --- the tool refuses what Alertmanager would accept ---------------------------------


@pytest.mark.asyncio
async def test_a_silence_with_no_matchers_is_refused() -> None:
    """Alertmanager accepts it, and it silences EVERYTHING."""
    with pytest.raises(ToolError, match="silences EVERYTHING"):
        await create_silence({"created_by": "zeus", "comment": "why"})


@pytest.mark.asyncio
@pytest.mark.parametrize("hours", [0, -1, MAX_SILENCE_HOURS + 1, 10_000])
async def test_an_unbounded_silence_is_refused(hours: float) -> None:
    """A silence that outlives the incident is how an outage goes unnoticed for
    a weekend."""
    with pytest.raises(ToolError, match="outlives the incident"):
        await create_silence(
            {"matchers": MATCHERS, "hours": hours, "created_by": "z", "comment": "w"}
        )


@pytest.mark.asyncio
async def test_an_unattributed_silence_is_refused() -> None:
    """One nobody can decide whether to keep."""
    with pytest.raises(ToolError, match="created_by"):
        await create_silence({"matchers": MATCHERS, "hours": 1, "comment": "why"})
    with pytest.raises(ToolError, match="comment"):
        await create_silence({"matchers": MATCHERS, "hours": 1, "created_by": "zeus"})


# --- the executor's three checks -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_action_never_reaches_the_connector() -> None:
    """And no approval can move it - that is what `too-wide-for-production` means."""
    performer = _Performer()
    action = _action(blast_radius=BlastRadius.CLUSTER)

    with pytest.raises(NotPermitted) as refused:
        await execute(
            action,
            perform=performer,
            connector="alertmanager",
            environment=Environment.PRODUCTION,
        )

    assert performer.calls == [], "a denied action reached the connector"
    assert refused.value.receipt.state is ExecutionState.SKIPPED
    assert "too-wide-for-production" in refused.value.receipt.detail


@pytest.mark.asyncio
async def test_an_action_needing_approval_without_one_is_refused() -> None:
    performer = _Performer()
    action = _action(blast_radius=BlastRadius.NAMESPACE)
    assert evaluate(action, environment=Environment.STAGING).decision is Decision.REQUIRE_APPROVAL

    with pytest.raises(NotPermitted, match="needs an approval"):
        await execute(
            action, perform=performer, connector="alertmanager", environment=Environment.STAGING
        )

    assert performer.calls == []


@pytest.mark.asyncio
async def test_an_approved_action_runs() -> None:
    """The control. An executor that refused everything would pass every test
    above and be indistinguishable from a broken one."""
    performer = _Performer()
    action = _action(blast_radius=BlastRadius.NAMESPACE)
    gate = ApprovalGate()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))
    approval = gate.respond(request.id, action, approver="alex", approve=True)

    receipt = await execute(
        action,
        perform=performer,
        connector="alertmanager",
        approval=approval,
        environment=Environment.STAGING,
    )

    assert receipt.state is ExecutionState.SUCCEEDED
    assert performer.calls == [("create_silence", action.parameters)]


@pytest.mark.asyncio
async def test_an_approval_for_a_changed_action_does_not_execute_it() -> None:
    """Approved as a dry run and executed after `dry_run` was cleared is the
    same id and a different act. Re-validated here rather than trusted from
    whoever passed it."""
    performer = _Performer()
    proposed = _action(blast_radius=BlastRadius.NAMESPACE)
    gate = ApprovalGate()
    request = gate.open_request(proposed, evaluate(proposed, environment=Environment.STAGING))
    approval = gate.respond(request.id, proposed, approver="alex", approve=True)

    widened = proposed.model_copy(update={"parameters": {**proposed.parameters, "hours": 24}})

    with pytest.raises(NotPermitted, match="no live approval"):
        await execute(
            widened,
            perform=performer,
            connector="alertmanager",
            approval=approval,
            environment=Environment.STAGING,
        )

    assert performer.calls == []


@pytest.mark.asyncio
async def test_an_expired_approval_does_not_execute() -> None:
    """`may_execute` re-checks the clock, so an approval held past its timeout
    does not still authorise a write."""
    performer = _Performer()
    action = _action(blast_radius=BlastRadius.NAMESPACE)
    gate = ApprovalGate(ttl=timedelta(minutes=30))
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))
    approval = gate.respond(request.id, action, approver="alex", approve=True)
    stale = approval.__class__(
        **{**vars(approval), "expires_at": datetime.now(tz=UTC) - timedelta(hours=1)}
    )

    with pytest.raises(NotPermitted, match="no live approval"):
        await execute(
            action,
            perform=performer,
            connector="alertmanager",
            approval=stale,
            environment=Environment.STAGING,
        )

    assert performer.calls == []


@pytest.mark.asyncio
async def test_an_allowed_action_needs_no_approval() -> None:
    """A dry run changes nothing, so requiring an approver for one would train
    people to click through the prompt that matters."""
    performer = _Performer()
    action = _action(blast_radius=BlastRadius.NAMESPACE, dry_run=True)

    receipt = await execute(
        action, perform=performer, connector="alertmanager", environment=Environment.STAGING
    )

    assert receipt.state is ExecutionState.DRY_RUN, (
        "a rehearsal reported as SUCCEEDED is how a plan looks applied when it is not"
    )
    assert performer.calls


# --- the receipt survives every outcome ------------------------------------------------


@pytest.mark.asyncio
async def test_a_refusal_still_produces_a_receipt() -> None:
    """An Action that was refused and an Action nobody tried look identical
    without one, and only the second is a bug."""
    action = _action(blast_radius=BlastRadius.CLUSTER)

    with pytest.raises(NotPermitted) as refused:
        await execute(
            action,
            perform=_Performer(),
            connector="alertmanager",
            environment=Environment.PRODUCTION,
        )

    assert refused.value.receipt.connector == "alertmanager"
    assert refused.value.receipt.detail, "a receipt with no detail explains nothing"


@pytest.mark.asyncio
async def test_a_failed_execution_is_recorded_as_failed_not_skipped() -> None:
    """ "It ran and broke" and "it never ran" are different facts and both need to
    survive."""
    action = _action(blast_radius=BlastRadius.NONE)

    with pytest.raises(NotPermitted) as failed:
        await execute(action, perform=_Performer(fail=True), connector="alertmanager")

    assert failed.value.receipt.state is ExecutionState.FAILED
    assert "ToolError" in failed.value.receipt.detail


@pytest.mark.asyncio
async def test_a_refusal_raises_rather_than_returning_a_state() -> None:
    """A caller that forgot to inspect a returned state would treat a refusal as
    a completed action."""
    with pytest.raises(NotPermitted):
        await execute(
            _action(blast_radius=BlastRadius.CLUSTER),
            perform=_Performer(),
            connector="alertmanager",
            environment=Environment.PRODUCTION,
        )


# --- what is actually sent -------------------------------------------------------------


def _alertmanager_replying(
    monkeypatch: pytest.MonkeyPatch, status: int = 200, body: Any = None
) -> list[httpx.Request]:
    """Capture the request without a socket. Returns the list it fills."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else {"silenceID": "abc"})

    transport = httpx.MockTransport(handle)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kwargs: real(transport=transport), raising=True
    )
    return seen


@pytest.mark.asyncio
async def test_a_silence_is_bounded_at_both_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    """`endsAt` is computed here rather than taken from the caller. A silence
    with no end is one nobody revisits, and Alertmanager will accept one."""
    seen = _alertmanager_replying(monkeypatch)

    await create_silence(
        {"matchers": MATCHERS, "hours": 2, "created_by": "zeus", "comment": "known symptom"}
    )

    body = json.loads(seen[0].content)
    starts = datetime.fromisoformat(body["startsAt"])
    ends = datetime.fromisoformat(body["endsAt"])

    assert ends - starts == timedelta(hours=2)
    assert body["createdBy"] == "zeus"
    assert body["comment"] == "known symptom"
    assert body["matchers"] == MATCHERS


@pytest.mark.asyncio
async def test_the_silence_goes_to_the_silences_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _alertmanager_replying(monkeypatch)

    await create_silence({"matchers": MATCHERS, "hours": 1, "created_by": "zeus", "comment": "why"})

    assert seen[0].url.path == "/api/v2/silences"
    assert seen[0].method == "POST"


@pytest.mark.asyncio
async def test_a_write_outside_the_allowlist_is_refused() -> None:
    """A separate allowlist from the reads on purpose: one list would make
    adding a write as easy as adding a read, and they are not the same act."""
    from connectors.alertmanager.tools import _post

    with pytest.raises(ToolError, match="/api/v2/silences"):
        await _post("/api/v2/alerts", {})


@pytest.mark.asyncio
async def test_a_rejected_write_is_reported_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 that came back as success would make a silence look applied when
    Alertmanager refused it."""
    _alertmanager_replying(monkeypatch, status=400, body={"error": "bad matcher"})

    with pytest.raises(ToolError, match="alertmanager returned 400"):
        await create_silence(
            {"matchers": MATCHERS, "hours": 1, "created_by": "zeus", "comment": "why"}
        )


@pytest.mark.asyncio
async def test_an_unreachable_alertmanager_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unattempted and failed are different, and only the second means the
    silence might exist."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    real = httpx.AsyncClient
    transport = httpx.MockTransport(refuse)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kwargs: real(transport=transport), raising=True
    )

    with pytest.raises(ToolError, match="unreachable"):
        await create_silence(
            {"matchers": MATCHERS, "hours": 1, "created_by": "zeus", "comment": "why"}
        )
