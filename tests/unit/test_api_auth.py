"""Who the caller is, and why the answer cannot come from the payload.

The approvals endpoint took the approver's name from the request body, and the
gate then checked that the approver was not the proposer - against a string the
caller had just chosen. Every test here is a way that could still be true.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.auth.dependencies import (
    AuthMisconfigured,
    Principal,
    Role,
    _parse,
    _principals,
    authenticate,
)
from api.main import create_app
from api.routers import approvals
from core.config import get_settings
from core.contracts.investigation import DEFAULT_TENANT
from core.store.investigations import InMemoryInvestigationStore
from core.store.providers import InMemoryProviderStore

GOOD = "alex:approver,admin=token-alex;svc-ci:operator=token-ci"

#: Everything else production insists on, so a test about TOKENS fails for that
#: reason and not because some unrelated variable was missing.
_PRODUCTION_SECRETS = (
    ("POSTGRES_PASSWORD", "x"),
    ("ALERTMANAGER_WEBHOOK_TOKEN", "x"),
    ("CERBERUS_MASTER_KEY", "0" * 64),
    ("S3_ACCESS_KEY", "x"),
    ("S3_SECRET_KEY", "x"),
    ("GITLAB_TOKEN", "x"),
    ("GITLAB_WEBHOOK_TOKEN", "x"),
    ("GITHUB_TOKEN", "x"),
    ("LLM_API_KEY", "x"),
)


class _Request:
    """The one thing `authenticate` reads off a request."""

    def __init__(self, header: str | None = None) -> None:
        self.headers = {"Authorization": header} if header is not None else {}


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tokens set, and both caches cleared around the test.

    `get_settings` and `_principals` are `lru_cache`d, so a test that set the
    variable without clearing them would assert against whatever the first test
    in the session loaded - an order-dependent test, which this repository has
    already been bitten by once.
    """
    monkeypatch.setenv("PANTHEON_API_TOKENS", GOOD)
    get_settings.cache_clear()
    _principals.cache_clear()
    yield
    get_settings.cache_clear()
    _principals.cache_clear()


# --- the table refuses what it cannot enforce ------------------------------------------


def test_two_principals_cannot_share_a_token() -> None:
    """An ambiguous identity would let one of them act as the other, and the
    trail would name the wrong person."""
    with pytest.raises(AuthMisconfigured, match="same token is configured"):
        _parse("alex:approver=shared;sam:approver=shared")


def test_a_token_with_no_roles_is_a_configuration_error() -> None:
    """It authenticates and can do nothing. That is not a read-only account -
    a read-only account says `viewer`."""
    with pytest.raises(AuthMisconfigured, match="can authenticate and do"):
        _parse("alex:=token-alex")


def test_an_unknown_role_is_refused_rather_than_dropped() -> None:
    """A dropped role silently reduces the set of people who can approve, and
    the symptom - one person's token stops working - reads as that person's
    problem rather than as a typo in a deployment."""
    with pytest.raises(AuthMisconfigured, match="role that does not exist"):
        _parse("alex:superuser=token-alex")


def test_an_entry_with_no_token_is_refused() -> None:
    with pytest.raises(AuthMisconfigured, match="no '=token' part"):
        _parse("alex:approver")


def test_an_entry_with_no_subject_is_refused() -> None:
    """A principal with no name cannot be recorded as having approved
    anything."""
    with pytest.raises(AuthMisconfigured, match="names no subject"):
        _parse(":approver=token-alex")


def test_a_well_formed_table_parses() -> None:
    """The control. A parser that refused everything would pass every test
    above."""
    table = _parse(GOOD)

    assert table["token-alex"] == Principal(
        subject="alex", roles=frozenset({Role.APPROVER, Role.ADMIN})
    )
    assert table["token-ci"].roles == frozenset({Role.OPERATOR})


# --- authentication ---------------------------------------------------------------------


@pytest.mark.usefixtures("configured")
def test_a_valid_bearer_token_names_its_principal() -> None:
    principal = authenticate(_Request("Bearer token-alex"))  # type: ignore[arg-type]

    assert principal.subject == "alex"


@pytest.mark.usefixtures("configured")
@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "token-alex",
        "Basic dG9rZW4tYWxleA==",
        "Bearer ",
        "Bearer token-alexx",
        "Bearer token-ale",
        "Bearer TOKEN-ALEX",
    ],
)
def test_nothing_but_the_exact_token_authenticates(header: str | None) -> None:
    """The prefix and suffix cases matter most. A comparison that stopped at
    the shorter length would admit `token-ale`, and one that used `startswith`
    would admit `token-alexx`.

    The scheme is checked too: a bare `Authorization: <token>` would mean a
    Basic header's base64 blob gets compared against a token, and a comparison
    that can never succeed is a login failing for a reason nobody can find.
    """
    with pytest.raises(HTTPException) as refused:
        authenticate(_Request(header))  # type: ignore[arg-type]

    assert refused.value.status_code == 401


@pytest.mark.usefixtures("configured")
def test_every_rejection_gives_the_same_message() -> None:
    """ "unknown token" and "no token" are different facts, and telling them
    apart tells whoever is guessing which half to work on."""
    messages = set()
    for header in (None, "Bearer wrong", "Basic abc"):
        with pytest.raises(HTTPException) as refused:
            authenticate(_Request(header))  # type: ignore[arg-type]
        messages.add(refused.value.detail)

    assert len(messages) == 1


def test_an_empty_table_authenticates_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug this shape invites: an empty credential matching an unset
    expectation, so no configuration means everybody is an admin."""
    monkeypatch.delenv("PANTHEON_API_TOKENS", raising=False)
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        with pytest.raises(HTTPException) as refused:
            authenticate(_Request("Bearer anything"))  # type: ignore[arg-type]
        assert refused.value.status_code == 401

        with pytest.raises(HTTPException):
            authenticate(_Request(None))  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


def test_production_refuses_to_start_without_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty table authenticating nobody is correct, and a deployment that
    meant to configure tokens and did not would discover it through a support
    ticket."""
    monkeypatch.setenv("PANTHEON_API_TOKENS", ";")
    monkeypatch.setenv("PANTHEON_ENV", "production")
    for variable, value in _PRODUCTION_SECRETS:
        monkeypatch.setenv(variable, value)
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        with pytest.raises(AuthMisconfigured, match="no PANTHEON_API_TOKENS"):
            _principals()
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


# --- roles -------------------------------------------------------------------------------


def test_admin_is_not_a_wildcard() -> None:
    """Implicit inheritance means the set of people who can approve is not the
    set of people listed as approvers, and that is exactly the question an
    audit asks."""
    admin = Principal(subject="root", roles=frozenset({Role.ADMIN}))

    assert admin.holds(Role.ADMIN)
    assert not admin.holds(Role.APPROVER)


def test_holding_any_of_the_named_roles_is_enough() -> None:
    principal = Principal(subject="alex", roles=frozenset({Role.APPROVER}))

    assert principal.holds(Role.ADMIN, Role.APPROVER)
    assert not principal.holds(Role.ADMIN, Role.OPERATOR)


# --- the endpoint that was resting on nothing ----------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=InMemoryProviderStore(master=b"0" * 32),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.usefixtures("configured")
def test_answering_an_approval_without_a_token_is_refused(client: TestClient) -> None:
    response = client.post(f"/approvals/{'0' * 8}-0000-0000-0000-000000000000", json={})

    assert response.status_code == 401


@pytest.mark.usefixtures("configured")
def test_a_principal_without_the_approver_role_is_forbidden(client: TestClient) -> None:
    """403 and not 401. The caller is who they say they are; they are not
    allowed to do this, and sending them back to fix their credentials would
    send them to the wrong place."""
    response = client.post(
        "/approvals/00000000-0000-0000-0000-000000000000",
        json={"approve": True, "reason": "", "action": {}},
        headers={"Authorization": "Bearer token-ci"},
    )

    assert response.status_code == 403
    assert "operator" in response.json()["detail"]


def test_the_response_body_has_no_approver_field() -> None:
    """The field is gone, not ignored. A body that still accepted `approver`
    would give a caller two ways to say who they are - one of them unverified,
    and nothing downstream able to tell which was used.
    """
    assert "approver" not in approvals.Response.model_fields


def test_the_endpoint_reads_the_approver_from_the_principal() -> None:
    """Asserted on the source, because the failure this prevents is a silent
    substitution: `approver=response.approver` and `approver=principal.subject`
    are one word apart and produce the same 200."""
    source = inspect.getsource(approvals.respond)

    assert "approver=principal.subject" in source
    assert "response.approver" not in source


def test_a_token_string_that_parses_to_nothing_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gap `REQUIRED_IN_PRODUCTION` cannot close.

    That check asks whether the variable is None. `PANTHEON_API_TOKENS=";;"`
    is a value - production starts - and it parses to no principals, so every
    gated endpoint is a 401 nobody can explain. Only the empty-TABLE check
    catches it, which is why both exist.
    """
    monkeypatch.setenv("PANTHEON_API_TOKENS", ";; ;")
    monkeypatch.setenv("PANTHEON_ENV", "production")
    for variable, value in _PRODUCTION_SECRETS:
        monkeypatch.setenv(variable, value)
    get_settings.cache_clear()
    _principals.cache_clear()
    try:
        assert get_settings().api.tokens is not None, "the fixture must pass the None check"

        with pytest.raises(AuthMisconfigured, match="no PANTHEON_API_TOKENS"):
            _principals()
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


# --- tenant scoping on the principal -------------------------------------------------


def test_a_token_without_a_tenant_gets_the_default() -> None:
    """A single-tenant deployment writes exactly what it wrote before, and
    still gets the mechanism rather than a bypass of it."""
    (principal,) = _parse("alex:approver=t1").values()

    assert principal.tenant == DEFAULT_TENANT
    assert principal.reads(DEFAULT_TENANT)
    assert not principal.reads("acme")


def test_a_tenant_is_parsed_off_the_identity() -> None:
    (principal,) = _parse("alex:approver@acme=t1").values()

    assert principal.subject == "alex"
    assert principal.roles == frozenset({Role.APPROVER})
    assert principal.tenant == "acme"


def test_an_empty_tenant_is_refused_rather_than_defaulted() -> None:
    """It would match nothing, so the account authenticates and sees no
    investigation at all - which reads as a broken deployment, not as a
    configuration error."""
    with pytest.raises(AuthMisconfigured, match="no tenant after it"):
        _parse("alex:approver@=t1")


def test_every_tenant_has_to_be_spelled() -> None:
    """`*` in the token table, in the same place it says everything else. A
    separate flag would be a second thing to read when answering "who can see
    this"."""
    (principal,) = _parse("support:viewer@*=t1").values()

    assert principal.reads_every_tenant
    assert principal.reads("acme") and principal.reads("globex")


def test_admin_does_not_read_every_tenant() -> None:
    """ADMIN is not a wildcard for roles and it is not one for tenants, for the
    same reason: implicit inheritance means the set of people who can read
    every tenant is not the set of people configured to."""
    (principal,) = _parse("root:admin@acme=t1").values()

    assert not principal.reads_every_tenant
    assert not principal.reads("globex")


def test_a_role_list_still_parses_with_a_tenant() -> None:
    """The `@` split happens before the `:` split, so a mistake in either
    would show up as roles or subject going missing."""
    (principal,) = _parse("alex:approver,operator@acme=t1").values()

    assert principal.roles == frozenset({Role.APPROVER, Role.OPERATOR})
    assert principal.subject == "alex"
    assert principal.tenant == "acme"
