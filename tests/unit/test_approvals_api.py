"""The approvals endpoint, and the checks it deliberately does not repeat.

The gate has held approvals since it landed and nothing could reach it: an
Action needing a person waited for one who had no way to answer.

Every safety check lives in `core/guardrails/approval_gate.py`. What these
assert is that the endpoint *reaches* it and reports what it said - a second
copy of the rules here is how the two drift, and the copy that drifts is always
the one nobody is testing.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.auth.dependencies import _principals
from api.main import create_app
from core.config import Environment, get_settings
from core.contracts.action import Action, BlastRadius
from core.contracts.evidence import ResourceRef
from core.guardrails.approval_gate import ApprovalGate
from core.guardrails.policy import Decision, evaluate
from core.store.investigations import InMemoryInvestigationStore
from core.store.providers import InMemoryProviderStore

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

#: Three principals, because the interesting tests need to tell them apart:
#: the proposer, a different approver, and somebody who authenticates fine and
#: is not allowed to approve anything.
TOKENS = {
    "alex": "token-alex",
    "sam": "token-sam",
    "zeus": "token-zeus",
    "morgan": "token-morgan",
}
TOKEN_CONFIG = (
    "alex:approver=token-alex;"
    "sam:approver=token-sam;"
    "zeus:approver=token-zeus;"
    "morgan:operator=token-morgan"
)


def _as(subject: str) -> dict[str, str]:
    """The header that makes the server believe who the caller is.

    A helper rather than a literal at each call, because the point of the whole
    change is that the identity is no longer something a test can type into a
    payload - it has to travel the same path a real caller's does.
    """
    return {"Authorization": f"Bearer {TOKENS[subject]}"}


@pytest.fixture(autouse=True)
def _configured_tokens(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Auth configured for the whole module, and both caches cleared around it.

    `get_settings` and `_principals` are both `lru_cache`d, so a test that set
    the variable without clearing them would run against whatever the first
    test in the session happened to load - which is an order-dependent test,
    and this file has been bitten by one before.
    """
    monkeypatch.setenv("PANTHEON_API_TOKENS", TOKEN_CONFIG)
    get_settings.cache_clear()
    _principals.cache_clear()
    yield
    get_settings.cache_clear()
    _principals.cache_clear()


class _Ticker:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> _Ticker:
    return _Ticker()


@pytest.fixture
def gate(clock: _Ticker) -> ApprovalGate:
    return ApprovalGate(clock=clock)


@pytest.fixture
def client(gate: ApprovalGate) -> Iterator[TestClient]:
    app = create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=InMemoryProviderStore(master=b"0" * 32),
        approval_gate=gate,
    )
    with TestClient(app) as test_client:
        yield test_client


def _action(blast_radius: BlastRadius = BlastRadius.NAMESPACE) -> Action:
    return Action(
        id=uuid4(),
        target=ResourceRef(kind="alert", name="CheckoutErrorRateHigh"),
        operation="create_silence",
        parameters={"hours": 1},
        blast_radius=blast_radius,
        # NOT a dry run. `Action.dry_run` defaults to True and the policy ALLOWS
        # a dry run outright, so a fixture that took the default never needed an
        # approver and every test below asserted the gate's behaviour on a
        # request the gate refuses to open.
        dry_run=False,
        reason="a known symptom",
        rollback="expire the silence",
        proposed_by="zeus",
        proposed_at=NOW,
    )


def _waiting(gate: ApprovalGate, action: Action) -> Any:
    """Open a request, having checked the policy actually asks for one.

    The assertion is the guard on the fixture: without it, an Action the policy
    allows outright makes every test here exercise nothing.
    """
    ruling = evaluate(action, environment=Environment.STAGING)
    assert ruling.decision is Decision.REQUIRE_APPROVAL, (
        f"the fixture builds an Action the policy rules {ruling.decision.value}; "
        "the gate refuses to open a request for one and these tests would be empty"
    )
    return gate.open_request(action, ruling)


def _body(action: Action, **overrides: Any) -> dict[str, Any]:
    payload = {
        "approve": True,
        "reason": "checked",
        "action": action.model_dump(mode="json"),
    }
    payload.update(overrides)
    return payload


# --- the queue ----------------------------------------------------------------------


def test_pending_requests_are_listed(client: TestClient, gate: ApprovalGate) -> None:
    action = _action()
    request = _waiting(gate, action)

    listed = client.get("/approvals").json()

    assert [entry["id"] for entry in listed] == [str(request.id)]
    assert listed[0]["proposed_by"] == "zeus"


def test_expired_requests_leave_the_queue(
    client: TestClient, gate: ApprovalGate, clock: _Ticker
) -> None:
    """A queue that grows forever teaches operators to ignore it, which is the
    one outcome an approval gate cannot survive."""
    _waiting(gate, _action())
    assert len(client.get("/approvals").json()) == 1

    clock.now = NOW + timedelta(hours=2)

    assert client.get("/approvals").json() == []


def test_a_request_reports_where_it_stands(client: TestClient, gate: ApprovalGate) -> None:
    request = _waiting(gate, _action())

    body = client.get(f"/approvals/{request.id}").json()

    assert body["state"] == "pending"
    assert body["rule"] == "default-requires-a-human"


def test_an_unknown_request_is_a_404(client: TestClient) -> None:
    assert client.get(f"/approvals/{uuid4()}").status_code == 404


# --- answering ------------------------------------------------------------------------


def test_an_approval_is_recorded(client: TestClient, gate: ApprovalGate) -> None:
    action = _action()
    request = _waiting(gate, action)

    body = client.post(f"/approvals/{request.id}", json=_body(action), headers=_as("alex")).json()

    assert body["state"] == "approved"
    assert body["answered_by"] == "alex"
    assert gate.state(request.id).value == "approved"


def test_a_rejection_is_recorded_with_its_reason(client: TestClient, gate: ApprovalGate) -> None:
    """The first thing read on a rejection."""
    action = _action()
    request = _waiting(gate, action)

    body = client.post(
        f"/approvals/{request.id}",
        json=_body(action, approve=False, reason="too wide"),
        headers=_as("alex"),
    ).json()

    assert body["state"] == "rejected"
    assert body["reason"] == "too wide"


# --- the gate's refusals reach the caller as 409, not 400 --------------------------------


def test_a_refusal_is_a_conflict_not_a_bad_request(client: TestClient, gate: ApprovalGate) -> None:
    """The request is well-formed; it is the STATE that says no. A 400 reads as
    "fix your payload", and the fix is never the payload."""
    action = _action()
    request = _waiting(gate, action)
    client.post(f"/approvals/{request.id}", json=_body(action), headers=_as("alex"))

    again = client.post(f"/approvals/{request.id}", json=_body(action), headers=_as("sam"))

    assert again.status_code == 409
    assert "already approved" in again.text


def test_self_approval_is_refused_through_the_endpoint(
    client: TestClient, gate: ApprovalGate
) -> None:
    """Not re-checked here. The endpoint reaches the gate and reports what it
    said - a second copy of the rule is how the two drift."""
    action = _action()
    request = _waiting(gate, action)

    refused = client.post(f"/approvals/{request.id}", json=_body(action), headers=_as("zeus"))

    assert refused.status_code == 409
    assert "cannot approve it" in refused.text


def test_an_approval_for_a_changed_action_is_refused(
    client: TestClient, gate: ApprovalGate
) -> None:
    """The Action is sent back in so the gate validates against the object the
    caller holds - the one about to be executed - rather than a stored copy that
    may already have diverged."""
    action = _action()
    request = _waiting(gate, action)
    widened = action.model_copy(update={"parameters": {"hours": 24}})

    refused = client.post(f"/approvals/{request.id}", json=_body(widened), headers=_as("alex"))

    assert refused.status_code == 409
    assert "has changed since approval was requested" in refused.text


def test_answering_an_expired_request_is_refused(
    client: TestClient, gate: ApprovalGate, clock: _Ticker
) -> None:
    action = _action()
    request = _waiting(gate, action)

    clock.now = NOW + timedelta(hours=2)
    refused = client.post(f"/approvals/{request.id}", json=_body(action), headers=_as("alex"))

    assert refused.status_code == 409
    assert "already expired" in refused.text


def test_answering_an_unknown_request_is_a_404_not_a_conflict(client: TestClient) -> None:
    """A typo and a rejected answer are different problems with different fixes."""
    response = client.post(f"/approvals/{uuid4()}", json=_body(_action()), headers=_as("alex"))

    assert response.status_code == 404


# --- what the endpoint never returns ------------------------------------------------------


def test_the_digest_is_not_exposed(client: TestClient, gate: ApprovalGate) -> None:
    """It is an internal check, not something an approver acts on - and
    publishing it invites a client that recomputes and pre-empts the gate."""
    request = _waiting(gate, _action())

    body = client.get(f"/approvals/{request.id}").text

    assert "action_digest" not in body


def test_the_app_always_has_a_gate() -> None:
    """A router reachable with no gate behind it would 500 on the first
    approval, at the worst possible moment."""
    app = create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=InMemoryProviderStore(master=b"0" * 32),
    )

    assert isinstance(app.state.approval_gate, ApprovalGate)
