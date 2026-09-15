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

from api.auth.dependencies import _principals
from api.main import create_app
from core.config import get_settings
from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind
from core.store.investigations import InMemoryInvestigationStore

#: The token table these tests authenticate against.
#:
#: `acme` and `globex` are two tenants; `support` reads every tenant and has to
#: say so with `@*`. `nobody` is an ADMIN in one tenant, which is what proves
#: ADMIN is not a cross-tenant wildcard.
TOKENS = (
    "reader:viewer@acme=acme-token;"
    "other:viewer@globex=globex-token;"
    "support:viewer@*=support-token;"
    "root:admin@acme=admin-token"
)
ACME = {"Authorization": "Bearer acme-token"}
GLOBEX = {"Authorization": "Bearer globex-token"}
SUPPORT = {"Authorization": "Bearer support-token"}
ADMIN = {"Authorization": "Bearer admin-token"}


def _investigation(created_at: datetime, tenant: str = "acme") -> Investigation:
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
        tenant=tenant,
    )


@pytest.fixture
def store() -> InMemoryInvestigationStore:
    return InMemoryInvestigationStore()


@pytest.fixture
def client(
    store: InMemoryInvestigationStore, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Both caches cleared around the test.

    `get_settings` and `_principals` are `lru_cache`d, so a test that set the
    variable without clearing them would assert against whatever the first test
    in the session loaded - an order-dependent test, which this repository has
    already been bitten by once.
    """
    monkeypatch.setenv("PANTHEON_API_TOKENS", TOKENS)
    get_settings.cache_clear()
    _principals.cache_clear()
    with TestClient(create_app(investigation_store=store)) as test_client:
        yield test_client
    get_settings.cache_clear()
    _principals.cache_clear()


@pytest.mark.asyncio
async def test_one_investigation_comes_back_whole(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    investigation = _investigation(datetime.now(UTC))
    await store.save(investigation)

    response = client.get(f"/investigations/{investigation.id}", headers=ACME)

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
    response = client.get(f"/investigations/{missing}", headers=ACME)

    assert response.status_code == 404, response.text
    assert str(missing) in response.json()["detail"]


def test_a_malformed_id_is_rejected_before_it_reaches_the_store(client: TestClient) -> None:
    assert client.get("/investigations/not-a-uuid", headers=ACME).status_code == 422


@pytest.mark.asyncio
async def test_the_list_is_newest_first(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    now = datetime.now(UTC)
    older, newer = _investigation(now - timedelta(minutes=5)), _investigation(now)
    await store.save(older)
    await store.save(newer)

    body = client.get("/investigations", headers=ACME).json()

    assert [entry["id"] for entry in body] == [str(newer.id), str(older.id)]


@pytest.mark.asyncio
async def test_the_list_honours_its_limit(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    now = datetime.now(UTC)
    for minutes in range(3):
        await store.save(_investigation(now - timedelta(minutes=minutes)))

    assert len(client.get("/investigations", params={"limit": 2}, headers=ACME).json()) == 2


def test_an_out_of_range_limit_is_refused(client: TestClient) -> None:
    """Bounded on both ends: 0 returns nothing usefully, and 1000 is a table scan."""
    assert client.get("/investigations", params={"limit": 0}, headers=ACME).status_code == 422
    assert client.get("/investigations", params={"limit": 101}, headers=ACME).status_code == 422


def test_an_empty_store_lists_nothing_rather_than_erroring(client: TestClient) -> None:
    assert client.get("/investigations", headers=ACME).json() == []


# --- tenant scoping -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_tenants_investigation_is_a_404_and_not_a_403(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """A 403 confirms the thing exists, and for tenant isolation existence is
    itself the disclosure: "that investigation is not yours" tells the caller
    another tenant had an incident, and an id is guessable enough to ask about.

    The message must match the missing case for the same reason.
    """
    theirs = _investigation(datetime.now(tz=UTC), tenant="globex")
    await store.save(theirs)

    response = client.get(f"/investigations/{theirs.id}", headers=ACME)
    missing = client.get(f"/investigations/{uuid4()}", headers=ACME)

    assert response.status_code == 404
    assert response.json()["detail"] == f"no investigation {theirs.id}"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_a_listing_shows_only_the_callers_tenant(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """The control and the claim in one. A filter that returned nothing would
    pass a test asserting the other tenant is absent."""
    now = datetime.now(tz=UTC)
    mine = _investigation(now, tenant="acme")
    theirs = _investigation(now - timedelta(minutes=1), tenant="globex")
    await store.save(mine)
    await store.save(theirs)

    listed = client.get("/investigations", headers=ACME).json()

    assert [row["id"] for row in listed] == [str(mine.id)]


@pytest.mark.asyncio
async def test_the_filter_runs_before_the_limit(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """Filtering afterwards returns a tenant with three runs among a hundred an
    empty page, which reads as "nothing happened" rather than as a paging bug.
    """
    now = datetime.now(tz=UTC)
    for index in range(20):
        await store.save(_investigation(now - timedelta(minutes=index), tenant="globex"))
    mine = _investigation(now - timedelta(hours=1), tenant="acme")
    await store.save(mine)

    listed = client.get("/investigations", params={"limit": 5}, headers=ACME).json()

    assert [row["id"] for row in listed] == [str(mine.id)]


@pytest.mark.asyncio
async def test_a_principal_configured_for_every_tenant_reads_both(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """`@*` is spelled in the token table. Without this the scoping could be a
    filter that matches nothing, and every test above would still pass."""
    now = datetime.now(tz=UTC)
    await store.save(_investigation(now, tenant="acme"))
    await store.save(_investigation(now - timedelta(minutes=1), tenant="globex"))

    listed = client.get("/investigations", headers=SUPPORT).json()

    assert {row["tenant"] for row in listed} == {"acme", "globex"}


@pytest.mark.asyncio
async def test_admin_is_not_a_cross_tenant_wildcard(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """The same argument `holds` makes about roles. Implicit inheritance means
    the set of people who can read every tenant is not the set of people
    configured to, and that is exactly the question an audit asks."""
    theirs = _investigation(datetime.now(tz=UTC), tenant="globex")
    await store.save(theirs)

    assert client.get(f"/investigations/{theirs.id}", headers=ADMIN).status_code == 404
    assert client.get("/investigations", headers=ADMIN).json() == []


@pytest.mark.asyncio
async def test_the_reads_need_a_token_at_all(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """Tenant scoping is meaningless without this: an unauthenticated caller
    has no tenant, and a scope everybody bypasses is a scope in name."""
    await store.save(_investigation(datetime.now(tz=UTC)))

    assert client.get("/investigations").status_code == 401
    assert client.get(f"/investigations/{uuid4()}").status_code == 401


@pytest.mark.asyncio
async def test_the_tenant_cannot_be_chosen_by_the_caller(
    client: TestClient, store: InMemoryInvestigationStore
) -> None:
    """A `?tenant=` would be a claim rather than a fact, and the endpoint would
    be an invitation to read somebody else's runs by typing their name."""
    now = datetime.now(tz=UTC)
    await store.save(_investigation(now, tenant="globex"))

    listed = client.get("/investigations", params={"tenant": "globex"}, headers=ACME).json()

    assert listed == []
