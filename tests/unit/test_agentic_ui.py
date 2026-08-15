"""Guards for the AG-UI / A2UI boundary.

Agent-generated UI is untrusted data, not code. These tests hold that line where
it can actually be checked: the allowlist is closed, the renderer rejects
anything outside it, identity cannot be claimed by an agent, no bespoke
WebSocket protocol comes back, and A2UI payloads are covered by the ADR 0005
redaction and schema guards like anything else an agent authors.

See docs/adr/0006-agentic-ui-protocols.md.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from core.cerberus.redaction import PLACEHOLDER, contains_secret, redact
from core.contracts.ui import (
    A2UI_VERSION,
    PANTHEON_CATALOG_ID,
    A2UIClientCapabilities,
    A2UIComponent,
    A2UIComponentType,
    A2UISurface,
    A2UISurfaceKind,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SURFACE_ID = UUID("00000000-0000-0000-0000-000000000001")
TS_CONTRACTS = REPO_ROOT / "dashboard/types/generated/contracts.ts"

# Components deliberately excluded from the allowlist, each for a stated reason.
# Media components fetch an agent-supplied URL, and that outbound request is an
# exfiltration channel; Modal can overlay a convincing fake credential prompt.
EXCLUDED_ON_PURPOSE = ("Image", "Video", "AudioPlayer", "Modal")


# ---------------------------------------------------------------------------
# the allowlist is closed, and the renderer rejects everything outside it
# ---------------------------------------------------------------------------


def test_renderer_rejects_component_types_outside_the_allowlist() -> None:
    """The rejection is structural: an unrenderable component cannot be built."""
    for rejected in (*EXCLUDED_ON_PURPOSE, "Script", "Html", "IFrame", "RawMarkup"):
        with pytest.raises(ValidationError):
            A2UIComponent(id="x", component=rejected)  # type: ignore[arg-type]


def test_every_allowlisted_component_is_constructible() -> None:
    """The other direction: nothing in the enum is unusable."""
    for allowed in A2UIComponentType:
        component = A2UIComponent(id=f"c-{allowed.value}", component=allowed)
        assert component.component is allowed


def test_media_and_modal_are_excluded_for_stated_reasons() -> None:
    """These are the components most likely to be re-added without thinking."""
    values = {member.value for member in A2UIComponentType}
    for excluded in EXCLUDED_ON_PURPOSE:
        assert excluded not in values, (
            f"{excluded} is back in the allowlist. Media components exfiltrate via "
            "the URL they fetch; Modal can impersonate a credential prompt. "
            "See docs/adr/0006-agentic-ui-protocols.md before re-adding."
        )


def test_allowlist_reaches_typescript_so_the_renderer_cannot_drift() -> None:
    """The renderer switches over the generated enum, not a hand-kept copy."""
    body = TS_CONTRACTS.read_text(encoding="utf-8")
    for allowed in A2UIComponentType:
        assert f'"{allowed.value}"' in body, (
            f"{allowed.value} did not reach the generated TypeScript; run `make codegen`"
        )


def test_advertised_capabilities_are_the_allowlist() -> None:
    """One artifact: allowlist, renderer and advertised capabilities cannot diverge.

    A2UI carries this in A2A message metadata; AG-UI defines no analog, so this
    is Pantheon convention - documented as such in ADR 0006.
    """
    capabilities = A2UIClientCapabilities()
    assert set(capabilities.components) == set(A2UIComponentType)
    assert capabilities.catalog_id == PANTHEON_CATALOG_ID
    assert capabilities.a2ui_version == A2UI_VERSION


def test_a2ui_version_is_the_stable_release_not_the_release_candidate() -> None:
    """v1.0 is a release candidate; the spec itself recommends v0.9.1."""
    assert A2UI_VERSION.startswith("v0.9"), (
        f"A2UI pinned to {A2UI_VERSION}; v1.0 is a release candidate - see the ROADMAP row"
    )


# ---------------------------------------------------------------------------
# identity cannot be claimed by an agent
# ---------------------------------------------------------------------------


def test_agents_cannot_set_surface_identity() -> None:
    """iconUrl and agentDisplayName are orchestrator-set, per the A2UI spec.

    Otherwise an agent presents itself as another agent, or as Pantheon.
    """
    component_fields = set(A2UIComponent.model_fields)
    for identity_field in ("icon_url", "agent_display_name"):
        assert identity_field not in component_fields, (
            f"A2UIComponent exposes {identity_field}; identity belongs on the surface, "
            "which the orchestrator builds"
        )

    surface_fields = set(A2UISurface.model_fields)
    assert {"icon_url", "agent_display_name"} <= surface_fields
    assert A2UISurface(id=SURFACE_ID, kind=A2UISurfaceKind.NOTICE, root="r").agent_display_name == (
        "Pantheon"
    )


# ---------------------------------------------------------------------------
# the bespoke protocol does not come back
# ---------------------------------------------------------------------------


def test_no_bespoke_websocket_protocol_reappears() -> None:
    """api/ws/ was superseded by AG-UI; a second protocol splits every client."""
    assert not (REPO_ROOT / "api" / "ws").exists(), (
        "api/ws/ is back. The UI protocol is AG-UI - see ADR 0006."
    )
    assert (REPO_ROOT / "api" / "agui" / "endpoint.py").is_file()


def test_agui_event_types_are_not_redefined() -> None:
    """Depend on the published schema; restating it is how the two drift."""
    ours = (REPO_ROOT / "core" / "contracts" / "ui.py").read_text(encoding="utf-8")
    for agui_event in ("RunStarted", "StateDelta", "ToolCallStart", "TextMessageContent"):
        assert agui_event not in ours, (
            f"{agui_event} is redefined in core/contracts/ui.py; import it from ag_ui.core"
        )


def test_custom_events_are_justified_and_few() -> None:
    """A Custom event needs the ADR 0006 test, and only one concept passes it."""
    from api.agui.translator import CUSTOM_EVENTS

    assert CUSTOM_EVENTS == ("pantheon.break_glass",), (
        "the set of Custom events changed; each one needs the ADR 0006 justification"
    )


def test_the_a2ui_envelope_guess_is_isolated_to_one_seam() -> None:
    """No canonical envelope exists yet, so the guess must live in one place."""
    from api.agui import a2ui_channel

    assert a2ui_channel.EVENT_NAME == "a2ui"

    body = (REPO_ROOT / "api" / "agui" / "a2ui_channel.py").read_text(encoding="utf-8")
    assert "UNRESOLVED" in body, "the seam must stay marked unresolved until a spec settles it"

    # Nothing else may hardcode the envelope name.
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.glob("api/agui/*.py")
        if path.name != "a2ui_channel.py" and 'EVENT_NAME = "a2ui"' in path.read_text("utf-8")
    ]
    assert not offenders, f"the A2UI envelope is duplicated outside the seam: {offenders}"


# ---------------------------------------------------------------------------
# cross-check with ADR 0005: agent-authored UI reaches the user
# ---------------------------------------------------------------------------

PLANTED = "hunter2-s3cr3t-Pa55phrase-9f2b"


def test_redaction_covers_a2ui_payloads() -> None:
    """An A2UI surface is agent-authored and reaches a human, so it is a sink.

    The schema scan catches secret-shaped *field names*; it cannot catch a secret
    pasted into a Text component's body. Redaction is what covers that, so the
    emission path must run it.
    """
    surface = A2UISurface(
        id=SURFACE_ID,
        kind=A2UISurfaceKind.REPORT,
        root="root",
        components=[
            A2UIComponent(id="root", component=A2UIComponentType.COLUMN, children=["t"]),
            A2UIComponent(
                id="t",
                component=A2UIComponentType.TEXT,
                text=f"The connection string was postgres://svc:{PLANTED}@db-01/pantheon",
            ),
        ],
        data_model={"note": f"api_key={PLANTED}"},
    )

    payload = json.loads(surface.model_dump_json())
    redacted = redact(payload, secrets=[PLANTED])

    assert not contains_secret(redacted, [PLANTED]), redacted
    assert PLACEHOLDER in json.dumps(redacted)


def test_ui_contracts_carry_no_secret_shaped_properties() -> None:
    """ADR 0005's schema scan must cover the UI contracts too."""
    from tests.unit.test_credential_safety import _is_secret_shaped

    for model in (A2UIComponent, A2UISurface, A2UIClientCapabilities):
        offenders = [name for name in model.model_fields if _is_secret_shaped(name)]
        assert not offenders, f"{model.__name__} exposes secret-shaped fields: {offenders}"
