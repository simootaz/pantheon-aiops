"""The AG-UI edge: what an internal event becomes on the wire.

Two properties carry this file. Every member of the Event union must translate -
an event that reaches the edge and vanishes looks to a client exactly like
nothing happening. And every state patch must be an append, because a `replace`
at an index applies cleanly and lands on the wrong element.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from ag_ui.core import (
    CustomEvent,
    EventType,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
)
from ag_ui.core import StepFinishedEvent as StepFinishedAgui
from ag_ui.core import StepStartedEvent as StepStartedAgui

from api.agui import a2ui_channel
from api.agui.encoder import SSE_MEDIA_TYPE, content_type_for, encode
from api.agui.endpoint import REQUIRED_COMPONENTS, unsupported_components
from api.agui.translator import (
    CUSTOM_EVENTS,
    DOMAIN_EVENT_MAPPING,
    UnmappedEvent,
    translate,
)
from core.contracts.action import Action, BlastRadius
from core.contracts.credentials import (
    AccessRequest,
    AuditEntry,
    AuditEvent,
    CredentialAction,
    CredentialRef,
    CredentialType,
)
from core.contracts.events import (
    AccessRequestedEvent,
    ApprovalRequestedEvent,
    BreakGlassEvent,
    Event,
    FindingProducedEvent,
    HypothesisProposedEvent,
    InvestigationCompletedEvent,
    InvestigationStartedEvent,
    LeaseExpiredEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TriggerReceivedEvent,
    VerdictReadyEvent,
)
from core.contracts.evidence import Evidence, EvidenceSource, MetricWindowPayload, ResourceRef
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind
from core.contracts.plan import PlanStep, StepStatus
from core.contracts.root_cause import RootCauseCategory, RootCauseHypothesis
from core.contracts.ui import A2UIComponentType
from core.contracts.verdict import Verdict
from core.ui import access_surface, approval_surface, renewal_surface

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
RUN = uuid4()


def _delta(event: Any) -> StateDeltaEvent:
    """The event as a StateDelta, asserted rather than assumed.

    `translate` is typed `list[BaseEvent]`, so mypy cannot narrow what comes
    back. Asserting the concrete type here is stronger than a `type: ignore`:
    a translation that started emitting the wrong FAMILY of event would still
    carry a `delta` attribute if it were a snapshot, and this catches it.
    """
    assert isinstance(event, StateDeltaEvent), f"expected a StateDelta, got {type(event).__name__}"
    return event


def _custom(event: Any) -> CustomEvent:
    assert isinstance(event, CustomEvent), f"expected a Custom, got {type(event).__name__}"
    return event


def _started(event: Any) -> RunStartedEvent:
    assert isinstance(event, RunStartedEvent), f"expected RunStarted, got {type(event).__name__}"
    return event


def _finished(event: Any) -> RunFinishedEvent:
    assert isinstance(event, RunFinishedEvent), f"expected RunFinished, got {type(event).__name__}"
    return event


def _step_start(event: Any) -> StepStartedAgui:
    assert isinstance(event, StepStartedAgui), f"expected StepStarted, got {type(event).__name__}"
    return event


def _step_finish(event: Any) -> StepFinishedAgui:
    assert isinstance(event, StepFinishedAgui), f"expected StepFinished, got {type(event).__name__}"
    return event


def _snapshot_of(event: Any) -> StateSnapshotEvent:
    assert isinstance(event, StateSnapshotEvent), f"expected a snapshot, got {type(event).__name__}"
    return event


def _trigger() -> Trigger:
    return Trigger(kind=TriggerKind.ALERT, received_at=NOW, source="alertmanager", title="x")


def _investigation() -> Investigation:
    return Investigation(
        id=RUN, state=InvestigationState.RUNNING, trigger=_trigger(), created_at=NOW
    )


def _finding() -> Finding:
    subject = ResourceRef(kind="pod", name="checkout-1")
    return Finding(
        id=uuid4(),
        agent="argus",
        kind=FindingKind.ANOMALY,
        title="memory crossed",
        severity=Severity.MEDIUM,
        confidence=0.8,
        detected_at=NOW,
        subject=subject,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="prometheus", query="up"),
                observed_at=NOW,
                summary="crossed",
                payload=MetricWindowPayload(metric="up"),
            )
        ],
    )


def _action() -> Action:
    return Action(
        id=uuid4(),
        target=ResourceRef(kind="deployment", name="checkout"),
        operation="rollout_restart",
        blast_radius=BlastRadius.SINGLE_WORKLOAD,
        reason="the verdict says the deploy is bad",
        proposed_by="zeus",
        proposed_at=NOW,
    )


def _access_request() -> AccessRequest:
    return AccessRequest(
        id=uuid4(),
        investigation_id=RUN,
        agent="argus",
        credential_ref=CredentialRef(id="c1", name="prod-postgres", type=CredentialType.DATABASE),
        action=CredentialAction.READ,
        reason="connection saturation may explain the p99 latency",
        requested_ttl_seconds=300,
        requested_at=NOW,
    )


def _every_event() -> list[Event]:
    """One instance of every member of the Event union."""
    return [
        TriggerReceivedEvent(investigation_id=RUN, trigger=_trigger()),
        InvestigationStartedEvent(investigation_id=RUN),
        InvestigationCompletedEvent(investigation_id=RUN, state="complete"),
        StepStartedEvent(investigation_id=RUN, agent="argus"),
        StepFinishedEvent(investigation_id=RUN, agent="argus"),
        FindingProducedEvent(investigation_id=RUN, finding=_finding()),
        HypothesisProposedEvent(
            investigation_id=RUN,
            hypothesis=RootCauseHypothesis(
                id=uuid4(),
                category=RootCauseCategory.MEMORY_LEAK,
                statement="memory leak on checkout",
                confidence=0.55,
                proposed_by="zeus",
            ),
        ),
        VerdictReadyEvent(
            investigation_id=RUN,
            verdict=Verdict(
                id=uuid4(),
                investigation_id=RUN,
                summary="observed, not an explanation",
                confidence=0.0,
                decided_at=NOW,
                steps=[PlanStep(agent="argus", reason="alert", status=StepStatus.COMPLETE)],
            ),
        ),
        ApprovalRequestedEvent(investigation_id=RUN, action=_action()),
        AccessRequestedEvent(investigation_id=RUN, request=_access_request()),
        LeaseExpiredEvent(investigation_id=RUN, lease_id=uuid4(), agent="argus"),
        BreakGlassEvent(invoked_by="alex", reason="suspected exfiltration"),
    ]


# --- every event translates ---------------------------------------------------------------


def test_every_member_of_the_event_union_has_a_translation() -> None:
    """An event that reaches the edge and vanishes looks to a client exactly
    like nothing happening, which is the worst failure a live view can have."""
    union = get_args(get_args(Event)[0])
    discriminators = {member.model_fields["type"].default for member in union}

    assert discriminators == set(DOMAIN_EVENT_MAPPING), (
        "the mapping table and the Event union disagree. Phase 0 documented a "
        "mapping for events the bus could not emit; this is what stops that."
    )

    for event in _every_event():
        assert translate(event, investigation=_investigation()), f"{event.type} produced nothing"


def test_an_event_outside_the_union_is_refused_rather_than_dropped() -> None:
    """Raised, not swallowed. Silence at the edge is indistinguishable from a
    run where nothing happened."""

    class _Alien:
        type = "invented"

    with pytest.raises(UnmappedEvent, match="no AG-UI translation"):
        translate(_Alien())  # type: ignore[arg-type]


# --- the state object is the Investigation --------------------------------------------------


def test_the_stream_opens_with_a_snapshot_of_the_investigation() -> None:
    """An empty screen followed by a populated one reads as a stall."""
    (event,) = translate(
        TriggerReceivedEvent(investigation_id=RUN, trigger=_trigger()),
        investigation=_investigation(),
    )

    assert _snapshot_of(event).snapshot["id"] == str(RUN)


def test_no_snapshot_is_invented_when_the_investigation_is_unknown() -> None:
    """A snapshot of a guess is worse than no snapshot: the client renders it
    and every later patch lands on the wrong base."""
    assert translate(TriggerReceivedEvent(investigation_id=RUN, trigger=_trigger())) == []


@pytest.mark.parametrize(
    ("event", "path"),
    [
        (FindingProducedEvent(investigation_id=RUN, finding=_finding()), "/findings/-"),
        (
            HypothesisProposedEvent(
                investigation_id=RUN,
                hypothesis=RootCauseHypothesis(
                    id=uuid4(),
                    category=RootCauseCategory.UNKNOWN,
                    statement="s",
                    confidence=0.5,
                    proposed_by="zeus",
                ),
            ),
            "/hypotheses/-",
        ),
    ],
)
def test_list_state_is_appended_never_replaced(event: Event, path: str) -> None:
    """RFC 6902's `-` means append, so a client reconstructs the same list
    without either side agreeing on an index.

    A `replace` at an index breaks the moment two agents finish out of order,
    and it breaks silently - the patch applies cleanly and lands on the wrong
    element.
    """
    (raw,) = translate(event)

    (operation,) = _delta(raw).delta
    assert operation["op"] == "add"
    assert operation["path"] == path


def test_the_verdict_is_replaced_because_there_is_only_ever_one() -> None:
    """Appending would build a list of verdicts on the client."""
    verdict = Verdict(
        id=uuid4(),
        investigation_id=RUN,
        summary="s",
        confidence=0.0,
        decided_at=NOW,
        steps=[],
    )

    (patch,) = translate(VerdictReadyEvent(investigation_id=RUN, verdict=verdict))

    operation = _delta(patch).delta[0]
    assert operation["op"] == "replace"
    assert operation["path"] == "/verdict"


def test_a_run_starts_and_finishes_with_the_investigation_id() -> None:
    """`thread_id` is what a reconnecting client resumes by. An invented one
    would make every reconnect open a new stream."""
    started = translate(InvestigationStartedEvent(investigation_id=RUN))
    finished = translate(InvestigationCompletedEvent(investigation_id=RUN, state="complete"))

    assert _started(started[0]).run_id == str(RUN)
    assert _started(started[0]).thread_id == str(RUN)
    # The completion is the LAST event: a state patch goes out before it, so a
    # client applies the terminal state before the stream closes on it.
    assert _finished(finished[-1]).run_id == str(RUN)


# --- break-glass is the one Custom event -----------------------------------------------------


def test_break_glass_emits_the_signal_and_the_record() -> None:
    """A dashboard acts on the Custom event; the audit trail is reconstructed
    from the patch. A client that missed the signal still ends up with the
    right Investigation."""
    entry = AuditEntry(
        id=uuid4(),
        at=NOW,
        event=AuditEvent.BREAK_GLASS,
        actor="alex",
        detail="pulled",
    )
    event = BreakGlassEvent(invoked_by="alex", reason="exfiltration", audit_entry=entry)

    signal, record = translate(event)

    assert _custom(signal).name == CUSTOM_EVENTS[0]
    assert _delta(record).delta[0]["path"] == "/audit/-"


def test_break_glass_without_an_entry_still_signals() -> None:
    """The signal is the urgent half. Withholding it because the record is
    missing would trade an immediate reaction for a bookkeeping detail."""
    (signal,) = translate(BreakGlassEvent(invoked_by="alex", reason="drill"))

    assert signal.type is EventType.CUSTOM


def test_only_one_custom_event_is_defined() -> None:
    """The test for an exception is not "is it ours" but "must the UI act the
    moment it arrives". Break-glass alone passes."""
    assert CUSTOM_EVENTS == ("pantheon.break_glass",)


# --- a revoked lease is not re-approvable -------------------------------------------------------


def test_an_expired_lease_raises_a_renewal_prompt() -> None:
    events = translate(
        LeaseExpiredEvent(investigation_id=RUN, lease_id=uuid4(), agent="argus", reason="expired")
    )

    assert len(events) == 2
    assert _custom(events[1]).name == a2ui_channel.EVENT_NAME


def test_a_revoked_lease_raises_no_prompt() -> None:
    """A revocation is a decision somebody just made. Re-prompting would put it
    back in front of the person who performed it as a question."""
    (only,) = translate(
        LeaseExpiredEvent(investigation_id=RUN, lease_id=uuid4(), agent="argus", reason="revoked")
    )

    assert _delta(only).delta[0]["path"] == "/findings/-"


# --- the A2UI seam -------------------------------------------------------------------------------


def test_an_approval_surface_carries_what_an_approver_needs_to_decide() -> None:
    """ "Approve action 7f3a?" is a prompt people learn to click through, and the
    whole gate then measures nothing."""
    surface = approval_surface(_action())
    text = " ".join(one.text or "" for one in surface.components)

    assert "rollout_restart" in text
    assert "deployment/checkout" in text
    assert "single_workload" in text
    assert "the verdict says the deploy is bad" in text


def test_an_access_surface_carries_the_hypothesis_being_tested() -> None:
    """Approving "an agent wants database access" is not a decision; approving
    a stated hypothesis is."""
    surface = access_surface(_access_request())
    text = " ".join(one.text or "" for one in surface.components)

    assert "connection saturation may explain the p99 latency" in text


def test_every_component_pantheon_emits_is_in_the_allowlist() -> None:
    """The allowlist is meaningful because only this module emits components. An
    allowlist over components an agent CHOSE would be a filter on hostile input;
    this is a statement about what this module does."""
    surfaces = [
        approval_surface(_action()),
        access_surface(_access_request()),
        renewal_surface(lease_id="l1", agent="argus"),
    ]

    for surface in surfaces:
        for component in surface.components:
            assert component.component in set(A2UIComponentType)


def test_no_surface_component_carries_a_url() -> None:
    """`Image` takes an ArtifactRef precisely so an agent cannot express an
    arbitrary destination. Nothing here should be emitting one at all."""
    for surface in (
        approval_surface(_action()),
        access_surface(_access_request()),
    ):
        rendered = surface.model_dump_json()
        assert "http://" not in rendered and "https://" not in rendered


def test_an_unknown_a2ui_message_type_is_refused() -> None:
    """Inventing one would put a message on the wire that no renderer has a
    branch for, and it would be dropped in silence."""
    with pytest.raises(ValueError, match="not an A2UI server-to-client message type"):
        a2ui_channel.to_wire(approval_surface(_action()), message_type="invented")


def test_the_wire_shape_is_built_in_exactly_one_place() -> None:
    """The envelope is a GUESS - no canonical AG-UI wrapper for an A2UI payload
    is specified. It is bounded to `to_wire` and `EVENT_NAME`, and this asserts
    the event goes out through that seam rather than around it."""
    event = a2ui_channel.surface_event(approval_surface(_action()))

    assert event.name == a2ui_channel.EVENT_NAME
    assert event.value is not None
    assert event.value["type"] == "createSurface"
    assert "surface" in event.value


# --- the returning message ---------------------------------------------------------------------


def test_a_client_action_nothing_routes_is_refused() -> None:
    """Accepted-and-ignored reads to whoever clicked it as the system having
    agreed."""
    with pytest.raises(a2ui_channel.UnknownClientAction, match="not one of"):
        a2ui_channel.from_wire({"actionName": "delete_everything", "surfaceId": str(uuid4())})


def test_a_message_naming_no_surface_is_refused() -> None:
    with pytest.raises(a2ui_channel.UnknownClientAction, match="no usable surface"):
        a2ui_channel.from_wire({"actionName": "approve", "surfaceId": "not-a-uuid"})


@pytest.mark.parametrize("action", ["approve", "reject", "grant", "deny"])
def test_the_four_real_decisions_parse(action: str) -> None:
    """The control. A parser that refused everything would pass both tests
    above."""
    surface_id = uuid4()

    response = a2ui_channel.from_wire(
        {
            "actionName": action,
            "surfaceId": str(surface_id),
            "sourceComponentId": "approve",
            "context": {"action_id": "7"},
        }
    )

    assert response.action_name == action
    assert response.surface_id == surface_id
    assert response.context == {"action_id": "7"}


def test_snake_case_keys_are_accepted_too() -> None:
    """A2UI is camelCase on the wire and Pantheon's contracts are snake_case.
    Accepting both means a client built against either reading works, and the
    alternative is a 400 nobody can debug from the message."""
    response = a2ui_channel.from_wire(
        {"action_name": "approve", "surface_id": str(uuid4()), "source_component_id": "b"}
    )

    assert response.action_name == "approve"


# --- the encoder ---------------------------------------------------------------------------------


def test_an_absent_accept_header_produces_sse_rather_than_binary() -> None:
    """The SDK treats an absent accept as "choose for me", and choosing a binary
    transport for a client that did not ask produces a stream nothing reads."""
    assert SSE_MEDIA_TYPE in content_type_for(None)


def test_the_content_type_matches_what_encode_produces() -> None:
    """Two places deciding the media type is two that can disagree, and the
    failure is a stream whose frames do not match its declared type - which a
    client reports as corrupt data rather than as a header bug."""
    event = translate(InvestigationStartedEvent(investigation_id=RUN))[0]

    framed = encode(event, accept=SSE_MEDIA_TYPE)

    assert content_type_for(SSE_MEDIA_TYPE).startswith("text/event-stream")
    assert framed.startswith("data: ")


# --- client capabilities -------------------------------------------------------------------------


def test_a_renderer_missing_a_required_component_is_named() -> None:
    """A dropped approval prompt is an approval nobody is asked for, and the run
    waits forever on a person who was never shown anything."""
    missing = unsupported_components([A2UIComponentType.TEXT, A2UIComponentType.CARD])

    assert "Button" in missing and "Row" in missing


def test_a_complete_renderer_is_reported_as_complete() -> None:
    """The control. A check that named something for every client would make the
    handshake reject everyone."""
    assert unsupported_components(list(REQUIRED_COMPONENTS)) == []


def test_the_required_set_is_what_the_surfaces_actually_use() -> None:
    """Demanding the whole component enum would reject renderers over components
    nothing ever sends."""
    used = {
        component.component
        for surface in (
            approval_surface(_action()),
            access_surface(_access_request()),
            renewal_surface(lease_id="l", agent="a"),
        )
        for component in surface.components
    }

    assert used == set(REQUIRED_COMPONENTS)


# --- the endpoint --------------------------------------------------------------------------------


def _client(store: Any, tokens: str) -> Any:
    from fastapi.testclient import TestClient

    from api.main import create_app

    return TestClient(create_app(investigation_store=store))


@pytest.mark.asyncio
async def test_another_tenants_run_cannot_be_streamed(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 rather than 403, the same as `GET /investigations/{id}`: a 403
    confirms the run exists, and for isolation existence is the disclosure."""
    from api.auth.dependencies import _principals
    from core.config import get_settings
    from core.store.investigations import InMemoryInvestigationStore

    monkeypatch.setenv("PANTHEON_API_TOKENS", "reader:viewer@acme=t1")
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        store = InMemoryInvestigationStore()
        theirs = _investigation().model_copy(update={"tenant": "globex"})
        await store.save(theirs)

        with _client(store, "t1") as client:
            response = client.get(f"/agui/{theirs.id}", headers={"Authorization": "Bearer t1"})

        assert response.status_code == 404
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


@pytest.mark.asyncio
async def test_an_unknown_run_is_a_404_with_the_same_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.auth.dependencies import _principals
    from core.config import get_settings
    from core.store.investigations import InMemoryInvestigationStore

    monkeypatch.setenv("PANTHEON_API_TOKENS", "reader:viewer@acme=t1")
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        missing = uuid4()
        with _client(InMemoryInvestigationStore(), "t1") as client:
            response = client.get(f"/agui/{missing}", headers={"Authorization": "Bearer t1"})

        assert response.status_code == 404
        assert response.json()["detail"] == f"no investigation {missing}"
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


@pytest.mark.asyncio
async def test_streaming_needs_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.auth.dependencies import _principals
    from core.config import get_settings
    from core.store.investigations import InMemoryInvestigationStore

    monkeypatch.setenv("PANTHEON_API_TOKENS", "reader:viewer@acme=t1")
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        with _client(InMemoryInvestigationStore(), "t1") as client:
            assert client.get(f"/agui/{uuid4()}").status_code == 401
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


@pytest.mark.asyncio
async def test_a_viewer_cannot_answer_an_approval_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every action the endpoint accepts is a decision. A read-only principal
    answering one would make the role name a description rather than a
    permission."""
    from api.auth.dependencies import _principals
    from core.config import get_settings
    from core.store.investigations import InMemoryInvestigationStore

    monkeypatch.setenv("PANTHEON_API_TOKENS", "reader:viewer@acme=t1")
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        store = InMemoryInvestigationStore()
        run = _investigation().model_copy(update={"tenant": "acme"})
        await store.save(run)

        with _client(store, "t1") as client:
            response = client.post(
                f"/agui/{run.id}/actions",
                json={"actionName": "approve", "surfaceId": str(uuid4())},
                headers={"Authorization": "Bearer t1"},
            )

        assert response.status_code == 403
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


def test_the_lease_finding_names_the_lease_and_the_reason() -> None:
    """`core/cerberus/lease.py` says an expiry must be surfaced rather than
    swallowed. This is the surfacing when the agent that lost it never ran
    again to report it."""
    lease_id = uuid4()

    (patch,) = translate(
        LeaseExpiredEvent(investigation_id=RUN, lease_id=lease_id, agent="argus", reason="revoked")
    )

    value = _delta(patch).delta[0]["value"]
    assert value["lease_id"] == str(lease_id)
    assert value["reason"] == "revoked"
    assert value["kind"] == "degraded"


def test_a_step_carries_the_agent_codename() -> None:
    """`stepName=codename` is what lets a dashboard label the row. An index
    would make every run's steps unnameable."""
    (started,) = translate(StepStartedEvent(investigation_id=RUN, agent="lethe"))
    (finished,) = translate(StepFinishedEvent(investigation_id=RUN, agent="lethe"))

    assert _step_start(started).step_name == "lethe"
    assert _step_finish(finished).step_name == "lethe"


def test_an_approval_request_becomes_a_surface_and_not_a_state_patch() -> None:
    """An approval PROMPT is not a fact about the run. Patching the prompt into
    state would render it as history the moment it arrived.

    The run's STATE is a fact about the run - the row says AWAITING_APPROVAL -
    and that is patched. The distinction is what this asserts: one surface as
    a Custom event, and the only state patch is `/state`, never the Action.
    """
    events = translate(ApprovalRequestedEvent(investigation_id=RUN, action=_action()))

    (surface,) = [e for e in events if e.type == EventType.CUSTOM]
    assert _custom(surface).name == a2ui_channel.EVENT_NAME
    for patch in (e for e in events if e.type == EventType.STATE_DELTA):
        assert [op["path"] for op in _delta(patch).delta] == ["/state"], (
            "the approval itself was patched into state"
        )


def test_time_does_not_leak_into_the_translation() -> None:
    """Two translations of the same event must produce the same patches, or
    replay reconstructs a different run each time it is read."""
    event = FindingProducedEvent(investigation_id=RUN, finding=_finding())

    first, second = translate(event)[0], translate(event)[0]

    assert _delta(first).delta == _delta(second).delta


def test_a_completed_run_carries_whether_it_was_partial() -> None:
    """`partial` is what tells a reader "nobody found anything" from "nobody
    looked". Dropping it at the edge would lose the distinction the whole
    DEGRADED path exists to preserve."""
    finished = translate(
        InvestigationCompletedEvent(investigation_id=RUN, state="complete", partial=True)
    )[-1]

    result = _finished(finished).result
    assert result is not None and result["partial"] is True


def test_the_snapshot_and_the_patches_describe_the_same_object() -> None:
    """A snapshot keyed differently from the patches is a client that applies
    them to nothing. `/findings/-` has to address the snapshot's own list."""
    (snapshot,) = translate(
        TriggerReceivedEvent(investigation_id=RUN, trigger=_trigger()),
        investigation=_investigation(),
    )
    (patch,) = translate(FindingProducedEvent(investigation_id=RUN, finding=_finding()))

    path = str(_delta(patch).delta[0]["path"]).removeprefix("/").removesuffix("/-")
    assert path in _snapshot_of(snapshot).snapshot, (
        f"the patch addresses /{path}, which the snapshot lacks"
    )


def test_investigation_ids_are_strings_on_the_wire() -> None:
    """AG-UI's run_id is a string. A UUID object would serialise differently
    depending on the encoder and a client comparing it against the id it asked
    for would find no match."""
    started = translate(InvestigationStartedEvent(investigation_id=RUN))[0]

    run_id = _started(started).run_id
    assert isinstance(run_id, str)
    assert UUID(run_id) == RUN


def test_a_finding_reaches_the_wire_whole() -> None:
    """Trimming it here would make the edge decide what a dashboard may show,
    and the dashboard is where that decision belongs."""
    finding = _finding()

    (patch,) = translate(FindingProducedEvent(investigation_id=RUN, finding=finding))

    value = _delta(patch).delta[0]["value"]
    assert value["title"] == finding.title
    assert value["evidence"]


def test_the_window_on_a_finding_survives_translation() -> None:
    windowed = _finding().model_copy(
        update={"window_start": NOW - timedelta(minutes=10), "window_end": NOW}
    )

    (patch,) = translate(FindingProducedEvent(investigation_id=RUN, finding=windowed))

    assert _delta(patch).delta[0]["value"]["window_end"] is not None


# --- the stream itself ---------------------------------------------------------------------------


def _authorised(store: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """An app with one viewer token, ready to stream."""
    from fastapi.testclient import TestClient

    from api.auth.dependencies import _principals
    from api.main import create_app
    from core.config import get_settings

    monkeypatch.setenv("PANTHEON_API_TOKENS", "reader:viewer,approver@acme=t1")
    get_settings.cache_clear()
    _principals.cache_clear()
    return TestClient(create_app(investigation_store=store))


def _ended_at_once(client: Any) -> Any:
    """Make every stream this app opens finish immediately.

    THE STREAM IS LIVE NOW, AND THIS CLIENT CANNOT READ A LIVE ONE
    ----------------------------------------------------------------
    `create_app` bridges the bus to the stream, so a stream stays open until
    the run finishes - which for a saved row nothing is running is forever.
    Starlette's TestClient consumes a whole response before returning and
    cannot close a stream part-way, so a plain `client.get` on a live stream
    hangs the suite: the guard whose failure mode is a hung runner.

    The tests that use this are about the OPENING frames and the headers, and
    a run that ends the instant it is subscribed to gives them exactly that.
    The bridge itself is tested where it can be observed: on the bus and on
    the queue, in `test_the_bridge_puts_translated_events_on_the_queue`.
    """
    import asyncio

    def _subscribe(investigation_id: Any, queue: asyncio.Queue[Any]) -> Any:
        for event in translate(InvestigationCompletedEvent(investigation_id=RUN, state="complete")):
            queue.put_nowait(event)
        return lambda: None

    client.app.state.agui_subscribe = _subscribe
    return client


@pytest.mark.asyncio
async def test_a_stream_opens_with_the_run_as_it_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty screen followed by a populated one reads as a stall, so the
    snapshot goes out before anything else - even when nothing is subscribed."""
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(f"/agui/{run.id}", headers={"Authorization": "Bearer t1"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert str(run.id) in response.text
    assert "STATE_SNAPSHOT" in response.text.upper().replace("_", "_")


@pytest.mark.asyncio
async def test_a_proxy_is_told_not_to_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A buffered event stream arrives in one lump when the run ends, which is
    the opposite of the point."""
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(f"/agui/{run.id}", headers={"Authorization": "Bearer t1"})

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_events_pushed_after_the_snapshot_reach_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stream is not just an opening snapshot. Without this the endpoint
    would look correct and deliver nothing that happened after connect."""
    import asyncio

    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)

    def _subscribe(investigation_id: Any, queue: asyncio.Queue[Any]) -> Any:
        for event in translate(FindingProducedEvent(investigation_id=RUN, finding=_finding())):
            queue.put_nowait(event)
        for event in translate(InvestigationCompletedEvent(investigation_id=RUN, state="complete")):
            queue.put_nowait(event)
        return lambda: None

    client = _authorised(store, monkeypatch)
    client.app.state.agui_subscribe = _subscribe
    with client:
        response = client.get(f"/agui/{run.id}", headers={"Authorization": "Bearer t1"})

    assert "memory crossed" in response.text
    assert "RUN_FINISHED" in response.text.upper()


@pytest.mark.asyncio
async def test_the_stream_closes_when_the_run_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream left open after a run finished is a client holding a connection
    for events that will never come, and a file descriptor per abandoned tab.

    Proven by the response completing at all: the generator loops forever until
    a terminal event arrives, so a stream that did not close would hang here.
    """
    import asyncio

    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)

    released: list[str] = []

    def _subscribe(investigation_id: Any, queue: asyncio.Queue[Any]) -> Any:
        for event in translate(InvestigationCompletedEvent(investigation_id=RUN, state="complete")):
            queue.put_nowait(event)
        return lambda: released.append("unsubscribed")

    client = _authorised(store, monkeypatch)
    client.app.state.agui_subscribe = _subscribe
    with client:
        client.get(f"/agui/{run.id}", headers={"Authorization": "Bearer t1"})

    assert released == ["unsubscribed"], "the subscription outlived the stream"


@pytest.mark.asyncio
async def test_an_approver_can_answer_a_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the viewer refusal. A route that rejected everyone would
    pass that test and make the endpoint useless."""
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)
    surface_id = uuid4()

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.post(
            f"/agui/{run.id}/actions",
            json={"actionName": "approve", "surfaceId": str(surface_id), "context": {"a": "1"}},
            headers={"Authorization": "Bearer t1"},
        )

    assert response.status_code == 200
    assert response.json()["surface_id"] == str(surface_id)
    assert response.json()["action_name"] == "approve"


@pytest.mark.asyncio
async def test_an_unroutable_action_is_a_400_and_not_a_silent_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepted-and-ignored reads to whoever clicked it as the system having
    agreed."""
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.post(
            f"/agui/{run.id}/actions",
            json={"actionName": "delete_everything", "surfaceId": str(uuid4())},
            headers={"Authorization": "Bearer t1"},
        )

    assert response.status_code == 400
    assert "not one of" in response.json()["detail"]


@pytest.mark.asyncio
async def test_answering_a_prompt_on_another_tenants_run_is_a_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    theirs = _investigation().model_copy(update={"tenant": "globex"})
    await store.save(theirs)

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.post(
            f"/agui/{theirs.id}/actions",
            json={"actionName": "approve", "surfaceId": str(uuid4())},
            headers={"Authorization": "Bearer t1"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_terminal_event_ends_the_generator_within_a_bounded_time() -> None:
    """The same claim as the test above, made so it FAILS rather than HANGS.

    A plant that removed the terminal check was caught by
    `test_the_stream_closes_when_the_run_finishes` - but only by making it hang
    until pytest was killed, which in CI times out the whole job instead of
    naming a broken assertion. A guard whose failure mode is a hung runner is a
    guard people learn to rerun rather than read.

    `asyncio.wait_for` turns it into a clean failure with a name attached.
    """
    import asyncio

    from api.agui.endpoint import _events_for
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation()
    await store.save(run)

    def _subscribe(investigation_id: Any, queue: asyncio.Queue[Any]) -> Any:
        for event in translate(InvestigationCompletedEvent(investigation_id=RUN, state="complete")):
            queue.put_nowait(event)
        return lambda: None

    class _App:
        state = type("S", (), {"agui_subscribe": staticmethod(_subscribe)})()

    class _Request:
        app = _App()

    async def _drain() -> list[Any]:
        return [event async for event in _events_for(_Request(), run.id, store)]  # type: ignore[arg-type]

    drained = await asyncio.wait_for(_drain(), timeout=5.0)

    assert drained[-1].type is EventType.RUN_FINISHED


# --- the catalog handshake -----------------------------------------------------------------------
#
# The module docstring claimed a client missing a component was "told at handshake
# time, in the response" for as long as nothing did it: `unsupported_components`
# was called only by the three tests above, and the dashboard sent its catalog to
# `POST /agui`, which has never existed. These go through a real request, because
# the tests above would keep passing if the endpoint stopped calling the function.

EVERY_COMPONENT = ",".join(member.value for member in A2UIComponentType)


async def _saved_run() -> tuple[Any, Any]:
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)
    return store, run


@pytest.mark.asyncio
async def test_a_client_that_cannot_render_a_button_is_refused_before_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """406, naming what it lacks.

    A Button is how an approval is answered. A client that cannot draw one would
    be sent the card, drop it, and leave the run in AWAITING_APPROVAL on a person
    who was never shown anything - which since the router began publishing
    approval surfaces is a thing that actually happens.
    """
    store, run = await _saved_run()

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(
            f"/agui/{run.id}",
            headers={"Authorization": "Bearer t1", "X-A2UI-Components": "Card,Row,Text"},
        )

    assert response.status_code == 406
    assert "Button" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_client_declaring_the_full_catalog_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control. A handshake that refused everybody would pass the test above."""
    store, run = await _saved_run()

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(
            f"/agui/{run.id}",
            headers={"Authorization": "Bearer t1", "X-A2UI-Components": EVERY_COMPONENT},
        )

    assert response.status_code == 200
    assert response.headers["x-a2ui-capabilities"] == "verified"


@pytest.mark.asyncio
async def test_an_undeclared_catalog_streams_and_says_it_was_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No header is a client that did not say, not one that renders nothing.

    Refusing it would lock out curl and every read-only consumer. But it is not
    silent: the header says the check did not happen, which is where somebody
    looks when a card never appeared.
    """
    store, run = await _saved_run()

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(f"/agui/{run.id}", headers={"Authorization": "Bearer t1"})

    assert response.status_code == 200
    assert response.headers["x-a2ui-capabilities"] == "undeclared"


@pytest.mark.asyncio
async def test_an_empty_declaration_is_a_client_that_renders_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`""` and no header are different answers, and only one is "unknown".

    A parser that collapsed both to `None` would wave through a client that said
    in so many words that it can draw nothing.
    """
    store, run = await _saved_run()

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(
            f"/agui/{run.id}", headers={"Authorization": "Bearer t1", "X-A2UI-Components": ""}
        )

    assert response.status_code == 406


@pytest.mark.asyncio
async def test_a_newer_client_is_not_refused_for_knowing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown names are dropped, not rejected.

    A client built against a later catalog declares components this server has
    never heard of. Refusing it would break every upgrade that lands client-first.
    """
    store, run = await _saved_run()

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(
            f"/agui/{run.id}",
            headers={
                "Authorization": "Bearer t1",
                "X-A2UI-Components": f"{EVERY_COMPONENT},Hologram,Sparkline",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_whitespace_around_names_is_not_a_missing_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`"Card, Row"` is how a person writes a list. Reading " Row" as unknown
    would refuse a complete renderer over a space."""
    store, run = await _saved_run()
    spaced = ", ".join(member.value for member in A2UIComponentType)

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(
            f"/agui/{run.id}", headers={"Authorization": "Bearer t1", "X-A2UI-Components": spaced}
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_another_tenants_run_is_a_404_even_for_an_inadequate_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tenant check runs first.

    A 406 for somebody else's investigation would confirm it exists, which is
    exactly the disclosure the 404 is there to prevent.
    """
    store, run = await _saved_run()
    theirs = run.model_copy(update={"id": uuid4(), "tenant": "globex"})
    await store.save(theirs)

    with _ended_at_once(_authorised(store, monkeypatch)) as client:
        response = client.get(
            f"/agui/{theirs.id}",
            headers={"Authorization": "Bearer t1", "X-A2UI-Components": "Text"},
        )

    assert response.status_code == 404


# --- the bridge: bus to stream, which nothing but a test had ever wired -------------
#
# `app.state.agui_subscribe` was read by the endpoint since it existed and set only
# by the tests above. In the running app the stream sent its snapshot and closed,
# and the dashboard reconnected every one to thirty seconds for as long as the
# page stayed open. These assert the seam at the level a TestClient can see it.


@pytest.mark.asyncio
async def test_the_app_wires_the_bus_to_the_stream() -> None:
    """The one line that was missing. Asserted on the app object rather than
    through a request, because a request on a live stream cannot be completed
    by this client - see `_ended_at_once`."""
    from api.main import create_app
    from core.bus import InMemoryEventBus

    app = create_app(event_bus=InMemoryEventBus())

    assert callable(getattr(app.state, "agui_subscribe", None)), (
        "the stream has no subscription source: it will send a snapshot and close"
    )


@pytest.mark.asyncio
async def test_the_bridge_puts_translated_events_on_the_queue() -> None:
    """Publish on the bus, receive AG-UI events on the stream's queue.

    Translated at the edge, per subscriber: the bus knows nothing of AG-UI.
    """
    import asyncio

    from api.main import create_app
    from core.bus import InMemoryEventBus

    bus = InMemoryEventBus()
    app = create_app(event_bus=bus)
    queue: asyncio.Queue[Any] = asyncio.Queue()

    unsubscribe = app.state.agui_subscribe(RUN, queue)
    await bus.publish(
        FindingProducedEvent(investigation_id=RUN, finding=_finding()), investigation_id=RUN
    )
    await bus.publish(
        InvestigationCompletedEvent(investigation_id=RUN, state="completed"), investigation_id=RUN
    )
    unsubscribe()
    await bus.publish(
        FindingProducedEvent(investigation_id=RUN, finding=_finding()), investigation_id=RUN
    )

    received = []
    while not queue.empty():
        received.append(queue.get_nowait())
    kinds = [event.type for event in received]

    assert EventType.STATE_DELTA in kinds, "the finding never reached the queue"
    assert kinds[-1] == EventType.RUN_FINISHED, "the run's end never reached the queue"
    assert kinds.count(EventType.STATE_DELTA) == 2, (
        "either the finding after unsubscribe arrived, or the completion's state patch did not"
    )


@pytest.mark.asyncio
async def test_another_investigations_events_do_not_reach_this_stream() -> None:
    """Fan-out is per investigation. A stream for one run receiving another's
    findings would show a reader somebody else's incident."""
    import asyncio
    from uuid import uuid4

    from api.main import create_app
    from core.bus import InMemoryEventBus

    bus = InMemoryEventBus()
    app = create_app(event_bus=bus)
    queue: asyncio.Queue[Any] = asyncio.Queue()
    app.state.agui_subscribe(RUN, queue)

    await bus.publish(
        FindingProducedEvent(investigation_id=uuid4(), finding=_finding()), investigation_id=uuid4()
    )

    assert queue.empty()


@pytest.mark.asyncio
async def test_the_generator_sends_a_keepalive_when_nothing_happens() -> None:
    """The module docstring promised a keep-alive comment. The generator used
    to `continue` on the timeout and send nothing, so an idle stream was closed
    by the proxy at its own timeout regardless - the keepalive existed in
    prose. Asserted on the generator directly, with the timeout shortened, so
    the test does not take twenty seconds to prove it."""
    import asyncio

    from api.agui import endpoint
    from core.store.investigations import InMemoryInvestigationStore

    store = InMemoryInvestigationStore()
    run = _investigation().model_copy(update={"tenant": "acme"})
    await store.save(run)

    class _Request:
        class app:
            class state:
                @staticmethod
                def agui_subscribe(investigation_id: Any, queue: asyncio.Queue[Any]) -> Any:
                    return lambda: None

    async def first_three() -> list[Any]:
        frames: list[Any] = []
        # A stand-in for the request: the generator reads `.app.state` and nothing
        # else off it, and building a real Request for that is scaffolding.
        async for frame in endpoint._events_for(_Request(), run.id, store):  # type: ignore[arg-type]
            frames.append(frame)
            if len(frames) >= 3:
                break
        return frames

    original = endpoint.KEEPALIVE_SECONDS
    endpoint.KEEPALIVE_SECONDS = 0.05
    try:
        # Bounded. A generator that swallowed the timeout would never yield a
        # second frame, and a test waiting for one would hang the suite - which
        # is exactly what a plant of the bare `continue` did before this bound
        # existed. Failing in two seconds is the guard; hanging is not.
        frames = await asyncio.wait_for(first_three(), timeout=2.0)
    except TimeoutError:
        pytest.fail("an idle stream sent nothing in 2 s: the keepalive is not being yielded")
    finally:
        endpoint.KEEPALIVE_SECONDS = original

    assert frames[0].type == EventType.STATE_SNAPSHOT
    assert frames[1] == endpoint.KEEPALIVE and frames[2] == endpoint.KEEPALIVE, (
        "an idle stream sent nothing between events"
    )
    assert endpoint.KEEPALIVE.startswith(":"), "a keepalive that is not an SSE comment is a frame"


# --- the state reaches a client that opened early ------------------------------------


def test_a_client_that_opened_during_pending_is_told_the_run_is_running() -> None:
    """Nothing else on the stream carries the state, and the opening snapshot is
    the only place it was ever written. Without this a client's `state` never
    moves from `pending`."""
    events = translate(InvestigationStartedEvent(investigation_id=RUN))

    patches = [e for e in events if e.type == EventType.STATE_DELTA]
    assert patches, "no state patch on InvestigationStarted"
    assert _delta(patches[0]).delta == [{"op": "replace", "path": "/state", "value": "running"}]


def test_the_terminal_state_is_patched_before_the_stream_closes() -> None:
    """A client applies the terminal state and then sees RUN_FINISHED. The
    other order would close the stream on a client still showing `running`."""
    from datetime import UTC, datetime

    closed = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    events = translate(
        InvestigationCompletedEvent(investigation_id=RUN, state="completed", completed_at=closed)
    )

    assert [e.type for e in events] == [EventType.STATE_DELTA, EventType.RUN_FINISHED]
    assert _delta(events[0]).delta == [
        {"op": "replace", "path": "/state", "value": "completed"},
        {"op": "replace", "path": "/completed_at", "value": closed.isoformat()},
    ]


def test_an_approval_request_moves_the_state_to_awaiting() -> None:
    """The run is waiting on a person. `Status` on the detail page reads the
    state and would otherwise show "live" on a run doing nothing until somebody
    clicks."""
    events = translate(ApprovalRequestedEvent(investigation_id=RUN, action=_action()))

    assert _delta(events[0]).delta == [
        {"op": "replace", "path": "/state", "value": "awaiting_approval"}
    ]
    assert events[1].type == EventType.CUSTOM, "the approval surface no longer follows the state"
