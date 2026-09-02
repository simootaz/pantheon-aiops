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
    assert _finished(finished[0]).run_id == str(RUN)


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
    """An approval is a prompt, not a fact about the run. Patching it into state
    would render it as history the moment it arrived."""
    (event,) = translate(ApprovalRequestedEvent(investigation_id=RUN, action=_action()))

    assert _custom(event).name == a2ui_channel.EVENT_NAME


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
    (finished,) = translate(
        InvestigationCompletedEvent(investigation_id=RUN, state="complete", partial=True)
    )

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
    (started,) = translate(InvestigationStartedEvent(investigation_id=RUN))

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

    with _authorised(store, monkeypatch) as client:
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

    with _authorised(store, monkeypatch) as client:
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

    with _authorised(store, monkeypatch) as client:
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

    with _authorised(store, monkeypatch) as client:
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

    with _authorised(store, monkeypatch) as client:
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
