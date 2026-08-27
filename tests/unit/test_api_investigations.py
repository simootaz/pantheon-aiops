"""The investigation read endpoints.

Read-only by design: an Investigation is created by a trigger, and a POST that
minted one would be a second way in with none of the classification a trigger
carries.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind
from core.store.investigations import InMemoryInvestigationStore


def _investigation(created_at: datetime) -> Investigation:
    return Investigation(
        id=uuid4(),
        state=InvestigationState.PENDING,
        trigger=Trigger(
            kind=TriggerKind.ALERT,
            received_at=created_at,
            source="alertmanager",
            title="CheckoutErrorRateHigh firing",
        ),
        created_at=created_at,
    )


@pytest.fixture
def store() -> InMemoryInvestigationStore:
    return InMemoryInvestigationStore()


@pytest.fixture
def client(store: InMemoryInvestigationStore) -> Iterator[TestClient]:
    with TestClient(create_app(investigation_store=store)) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_one_investigation_comes_back_whole(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    investigation = _investigation(datetime.now(UTC))
    await store.save(investigation)

    response = client.get(f"/investigations/{investigation.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(investigation.id)
    assert body["trigger"]["source"] == "alertmanager"
    assert body["state"] == "pending"


def test_an_unknown_id_is_a_404_not_an_empty_body(client: TestClient) -> None:
    """The window between an accepted alert and Zeus writing the first row.

    The receiver returns 202 with an id immediately; a caller polling it sees
    404 and then the run. An empty 200 would read as "exists, nothing in it".
    """
    missing = uuid4()
    response = client.get(f"/investigations/{missing}")

    assert response.status_code == 404, response.text
    assert str(missing) in response.json()["detail"]


def test_a_malformed_id_is_rejected_before_it_reaches_the_store(client: TestClient) -> None:
    assert client.get("/investigations/not-a-uuid").status_code == 422


@pytest.mark.asyncio
async def test_the_list_is_newest_first(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    now = datetime.now(UTC)
    older, newer = _investigation(now - timedelta(minutes=5)), _investigation(now)
    await store.save(older)
    await store.save(newer)

    body = client.get("/investigations").json()

    assert [entry["id"] for entry in body] == [str(newer.id), str(older.id)]


@pytest.mark.asyncio
async def test_the_list_honours_its_limit(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    now = datetime.now(UTC)
    for minutes in range(3):
        await store.save(_investigation(now - timedelta(minutes=minutes)))

    assert len(client.get("/investigations", params={"limit": 2}).json()) == 2


def test_an_out_of_range_limit_is_refused(client: TestClient) -> None:
    """Bounded on both ends: 0 returns nothing usefully, and 1000 is a table scan."""
    assert client.get("/investigations", params={"limit": 0}).status_code == 422
    assert client.get("/investigations", params={"limit": 101}).status_code == 422


def test_an_empty_store_lists_nothing_rather_than_erroring(client: TestClient) -> None:
    assert client.get("/investigations").json() == []
