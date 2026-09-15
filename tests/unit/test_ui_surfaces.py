"""Surface construction, and the one module that turns a reference into a URL.

`artifact_resolution` mirrors `core/cerberus/redemption.py` exactly: there,
plaintext is produced in one place agents cannot import; here, a fetchable
destination is. The tests that matter are the refusals - a resolver that
resolved everything would pass any test asserting a URL comes back.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.contracts.action import Action, BlastRadius
from core.contracts.credentials import (
    AccessRequest,
    CredentialAction,
    CredentialRef,
    CredentialType,
)
from core.contracts.evidence import ResourceRef
from core.contracts.ui import A2UIComponentType, ArtifactKind, ArtifactRef
from core.ui import access_surface, approval_surface, renewal_surface
from core.ui import components as build
from core.ui.artifact_resolution import (
    URL_TTL,
    ArtifactNotResolvable,
    resolve,
    resolver_for,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
RUN = uuid4()


def _action(**overrides: object) -> Action:
    fields: dict[str, object] = {
        "id": uuid4(),
        "target": ResourceRef(kind="deployment", name="checkout"),
        "operation": "rollout_restart",
        "blast_radius": BlastRadius.SINGLE_WORKLOAD,
        "reason": "the verdict says the deploy is bad",
        "proposed_by": "zeus",
        "proposed_at": NOW,
    }
    fields.update(overrides)
    return Action(**fields)  # type: ignore[arg-type]


def _request() -> AccessRequest:
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


def _ref(key: str = "run-1/plot.png", investigation_id: object = None) -> ArtifactRef:
    return ArtifactRef(
        key=key,
        investigation_id=investigation_id if investigation_id is not None else RUN,  # type: ignore[arg-type]
        kind=ArtifactKind.IMAGE,
    )


def _signer(*, bucket: str, key: str, expires_in: int) -> str:
    return f"https://storage.internal/{bucket}/{key}?expires={expires_in}"


# --- one builder per type, and the fields that type takes ------------------------------


def test_a_divider_cannot_carry_text() -> None:
    """One builder per type means the SIGNATURE says which fields it takes. A
    Divider carrying text is not something a caller can express by accident."""
    with pytest.raises(TypeError):
        build.divider("d", "some text")  # type: ignore[call-arg]


def test_a_text_component_cannot_carry_an_action() -> None:
    """A Text that could act is a hidden button."""
    assert build.text("t", "hello").action is None


def test_an_image_takes_a_reference_and_there_is_no_url_parameter() -> None:
    """A builder accepting a URL "just for internal use" would put the
    exfiltration path back, because the component travels to a browser either
    way."""
    import inspect

    from pydantic import ValidationError

    assert "url" not in inspect.signature(build.image).parameters
    with pytest.raises(ValidationError):
        build.image("i", "https://evil.example/x.png")  # type: ignore[arg-type]

    component = build.image("i", _ref())
    assert component.artifact_ref is not None
    assert component.text is None


def test_a_button_must_name_an_action() -> None:
    """A Button with no action does nothing when pressed, which on an approval
    prompt is indistinguishable from one whose answer was lost."""
    with pytest.raises(TypeError):
        build.button("b", "Approve")  # type: ignore[call-arg]


def test_an_input_must_say_where_it_writes() -> None:
    """An input with nowhere to write collects a value the surface discards, and
    looks identical to one that works until somebody types in it."""
    with pytest.raises(TypeError):
        build.text_field("f", "Name")  # type: ignore[call-arg]

    assert build.text_field("f", "Name", data_path="/name").data_path == "/name"


def test_every_builder_produces_an_allowlisted_component() -> None:
    """An unrenderable component cannot be constructed in the first place."""
    made = [
        build.row("a"),
        build.column("b"),
        build.card("c"),
        build.listing("d"),
        build.text("e", "x"),
        build.image("f", _ref()),
        build.icon("g", "warning"),
        build.divider("h"),
        build.text_field("i", "l", data_path="/p"),
        build.check_box("j", "l", data_path="/p"),
        build.choice_picker("k", "l", data_path="/p"),
        build.date_time_input("l", "l", data_path="/p"),
        build.button("m", "l", action="approve"),
    ]

    assert {one.component for one in made} == set(A2UIComponentType)


# --- the approval card carries what an approver needs -----------------------------------


def test_the_approval_card_is_not_just_an_id() -> None:
    """ "Approve action 7f3a?" is a prompt people learn to click through, and a
    gate answered by reflex measures nothing - which is worse than no gate,
    because the trail then records a decision nobody made."""
    surface = approval_surface(_action())
    shown = " ".join(one.text or "" for one in surface.components)

    assert "rollout_restart" in shown
    assert "deployment/checkout" in shown
    assert "single_workload" in shown
    assert "the verdict says the deploy is bad" in shown


def test_a_wide_action_shows_its_rollback() -> None:
    """The moment somebody is deciding is the worst moment to be working out
    whether it can be reversed."""
    wide = _action(
        blast_radius=BlastRadius.NAMESPACE, rollback="roll back to the previous revision"
    )

    shown = " ".join(one.text or "" for one in approval_surface(wide).components)

    assert "roll back to the previous revision" in shown


def test_the_card_names_the_proposer_not_the_approver() -> None:
    """`agent_display_name` says who is ASKING. The gate separately refuses a
    proposer approving their own request, and this label is what makes that
    check legible to whoever is reading."""
    assert approval_surface(_action()).agent_display_name == "zeus"


def test_the_access_card_carries_the_hypothesis() -> None:
    """`AccessRequest.reason` is a required contract field rather than a note,
    and this is where that pays off."""
    shown = " ".join(one.text or "" for one in access_surface(_request()).components)

    assert "connection saturation may explain the p99 latency" in shown


def test_no_surface_renders_the_credential_itself() -> None:
    """A surface carries a CredentialRef, which identifies without disclosing."""
    rendered = access_surface(_request()).model_dump_json()

    assert "prod-postgres" in rendered, "the reference is shown"
    assert "password" not in rendered and "secret" not in rendered


def test_every_button_names_an_action_the_inbound_path_routes() -> None:
    """A button naming an action `a2ui_channel` does not route is a button that
    does nothing when pressed."""
    from api.agui.a2ui_channel import CLIENT_ACTIONS

    for surface in (
        approval_surface(_action()),
        access_surface(_request()),
        renewal_surface(lease_id="l1", agent="argus"),
    ):
        buttons = [one for one in surface.components if one.component is A2UIComponentType.BUTTON]
        assert buttons, f"{surface.kind} offers no way to answer"

        for component in surface.components:
            if component.component is A2UIComponentType.BUTTON:
                # Asserted on the BUTTON, not on "every action that exists".
                # The first version skipped a component whose action was None,
                # so a plant that dropped the action entirely passed - the
                # fixture could not express the claim it was making.
                assert component.action is not None, f"{component.id} does nothing when pressed"
                assert component.action.event_name in CLIENT_ACTIONS
            else:
                assert component.action is None, f"{component.id} is a hidden button"


def test_every_child_named_by_a_container_exists() -> None:
    """A child id nothing defines renders as a gap, and a gap where the Approve
    button should be is an approval nobody can give."""
    for surface in (
        approval_surface(_action()),
        access_surface(_request()),
        renewal_surface(lease_id="l1", agent="argus"),
    ):
        defined = {one.id for one in surface.components}
        for component in surface.components:
            missing = [child for child in component.children if child not in defined]
            assert not missing, f"{surface.kind}: {component.id} names {missing}"
        assert surface.root in defined


# --- resolution: the exfiltration path this closes ----------------------------------------


def test_a_reference_from_another_investigation_is_refused() -> None:
    """The whole point. A cross-investigation reference is how one run would
    exfiltrate another's artifacts by naming their keys."""
    theirs = _ref(investigation_id=uuid4())

    with pytest.raises(ArtifactNotResolvable, match="cross-investigation"):
        resolve(theirs, investigation_id=RUN, signer=_signer)


def test_a_matching_reference_resolves() -> None:
    """The control. A resolver that refused everything would pass every refusal
    test here and render no image ever."""
    url = resolve(_ref(), investigation_id=RUN, signer=_signer)

    assert "run-1/plot.png" in url


def test_the_bucket_is_fixed_server_side_and_not_taken_from_the_reference() -> None:
    """What makes "no arbitrary destination is expressible" true rather than
    descriptive: an ArtifactRef carries a key and nothing that could name a
    different bucket."""
    seen: dict[str, str] = {}

    def _recording(*, bucket: str, key: str, expires_in: int) -> str:
        seen["bucket"] = bucket
        return "https://x/y"

    resolve(_ref(), investigation_id=RUN, signer=_recording)

    from core.config import get_settings

    assert seen["bucket"] == get_settings().object_storage.bucket_artifacts


@pytest.mark.parametrize(
    "hostile",
    ["../../etc/passwd", "run-1/../../secrets", "run-1/..", "/leading", "has space", ""],
)
def test_a_key_that_could_address_something_else_is_refused(hostile: str) -> None:
    """A value checked once it is already inside a URL is a value checked too
    late - the same lesson the Loki and GitHub connectors record."""
    with pytest.raises(ArtifactNotResolvable):
        resolve(_ref(key=hostile), investigation_id=RUN, signer=_signer)


def test_no_signer_refuses_rather_than_returning_an_unsigned_url() -> None:
    """An unsigned URL either fails at fetch - which reads as a broken image -
    or works, which would mean the bucket is public."""
    with pytest.raises(ArtifactNotResolvable, match="no signer is configured"):
        resolve(_ref(), investigation_id=RUN, signer=None)


def test_the_url_is_short_lived() -> None:
    """For the reason a lease is short: the window in which a leaked URL is
    worth anything is exactly this long."""
    seen: dict[str, int] = {}

    def _recording(*, bucket: str, key: str, expires_in: int) -> str:
        seen["expires_in"] = expires_in
        return "https://x/y"

    resolve(_ref(), investigation_id=RUN, signer=_recording)

    assert seen["expires_in"] == int(URL_TTL.total_seconds())
    assert URL_TTL.total_seconds() <= 900, "a URL good for hours is one good tomorrow"


def test_a_bound_resolver_still_checks_the_investigation() -> None:
    """The convenience wrapper must not be the way around the check."""
    bound = resolver_for(_signer)

    assert bound(_ref(), RUN)
    with pytest.raises(ArtifactNotResolvable, match="cross-investigation"):
        bound(_ref(investigation_id=uuid4()), RUN)


def test_no_name_from_the_resolver_is_re_exported_by_the_package() -> None:
    """What `__all__` actually buys, which is less than it looks.

    A first version of this asserted `not hasattr(core.ui, "artifact_resolution")`
    and failed: importing the submodule anywhere - including from this test -
    binds it as an attribute of the package, so the module is always reachable
    as `core.ui.artifact_resolution` whatever `__all__` says.

    So the real boundary is the IMPORT GRAPH, and
    `tests/unit/test_credential_safety.py` is what enforces it - the same
    mechanism that keeps `core.cerberus.redemption` away from agents. What
    `__all__` buys is narrower and still worth having: no name from the resolver
    arrives through `from core.ui import ...`.
    """
    import core.ui as package
    from tests.unit.test_credential_safety import FORBIDDEN_FOR_AGENTS

    assert "core.ui.artifact_resolution" in FORBIDDEN_FOR_AGENTS, (
        "the import-graph guard is the boundary; if it stops covering this "
        "module, nothing else does"
    )
    exported = package.__all__
    assert "artifact_resolution" not in exported
    assert "resolve" not in exported and "resolver_for" not in exported
