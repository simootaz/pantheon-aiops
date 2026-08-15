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
    A2UIAction,
    A2UIClientCapabilities,
    A2UIComponent,
    A2UIComponentType,
    A2UISurface,
    A2UISurfaceKind,
    ArtifactRef,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SURFACE_ID = UUID("00000000-0000-0000-0000-000000000001")
TS_CONTRACTS = REPO_ROOT / "dashboard/types/generated/contracts.ts"

# Components deliberately excluded from the allowlist, each for a stated reason.
# Image is NOT here: it was re-admitted reference-based, taking an ArtifactRef
# rather than a URL. Video and AudioPlayer stay out until something needs them.
EXCLUDED_ON_PURPOSE = ("Video", "AudioPlayer", "Modal")

# Property names that would let an agent name a destination the browser fetches.
URL_SHAPED = ("url", "src", "href", "uri", "source", "endpoint", "link")


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


def test_speculative_and_impersonating_components_stay_excluded() -> None:
    """These are the components most likely to be re-added without thinking."""
    values = {member.value for member in A2UIComponentType}
    for excluded in EXCLUDED_ON_PURPOSE:
        assert excluded not in values, (
            f"{excluded} is back in the allowlist. Modal can impersonate a credential "
            "prompt; Video and AudioPlayer are speculative and would need the same "
            "ArtifactRef treatment as Image. See docs/adr/0006-agentic-ui-protocols.md."
        )


def test_image_is_allowed_but_only_by_reference() -> None:
    """Image is renderable; a destination is not expressible."""
    assert A2UIComponentType.IMAGE in set(A2UIComponentType)

    component = A2UIComponent(
        id="img",
        component=A2UIComponentType.IMAGE,
        artifact_ref=ArtifactRef(key="flame-graph.svg", investigation_id=SURFACE_ID),
    )
    assert component.artifact_ref is not None
    assert component.artifact_ref.key == "flame-graph.svg"


def test_artifact_ref_cannot_express_a_destination() -> None:
    """No URL, no host, no bucket. The bucket is fixed server-side."""
    fields = set(ArtifactRef.model_fields)
    # Substring, not exact match: `image_url` is as much a destination as `url`.
    for nameable in ("url", "bucket", "host", "endpoint", "src", "uri"):
        offenders = [name for name in fields if nameable in name.lower()]
        assert not offenders, (
            f"ArtifactRef exposes {offenders}; an agent must not be able to name a "
            "destination. See docs/adr/0006-agentic-ui-protocols.md."
        )
    assert "investigation_id" in fields, (
        "ArtifactRef must carry its investigation so cross-investigation refs are refusable"
    )


def test_no_a2ui_component_accepts_a_free_form_url_in_any_language() -> None:
    """The invariant must hold on the generated artifacts, not only in Python.

    Surface identity (icon_url) is deliberately out of scope: it lives on
    A2UISurface and is set by the orchestrator, never by an agent.
    """
    for model in (A2UIComponent, ArtifactRef, A2UIAction):
        offenders = [
            name for name in model.model_fields if any(t in name.lower() for t in URL_SHAPED)
        ]
        assert not offenders, f"{model.__name__} accepts a free-form URL: {offenders}"

    schema = json.loads(
        (REPO_ROOT / "core/contracts/export/pantheon.schema.json").read_text(encoding="utf-8")
    )
    for def_name in ("A2UIComponent", "ArtifactRef", "A2UIAction"):
        properties = schema["$defs"][def_name].get("properties", {})
        offenders = [p for p in properties if any(t in p.lower() for t in URL_SHAPED)]
        assert not offenders, f"generated schema: {def_name} accepts a URL: {offenders}"

    go_body = (REPO_ROOT / "pkg/contracts/contracts.gen.go").read_text(encoding="utf-8")
    ts_body = TS_CONTRACTS.read_text(encoding="utf-8")
    for language, body in (("Go", go_body), ("TypeScript", ts_body)):
        for token in ("ArtifactUrl", "artifact_url", "ImageUrl", "image_url"):
            assert token not in body, f"generated {language} exposes {token}"


def test_artifact_resolution_is_off_limits_to_agents() -> None:
    """Mirrors the redemption boundary: agents hold references, servers resolve."""
    from tests.unit.test_credential_safety import FORBIDDEN_FOR_AGENTS

    assert "core.ui.artifact_resolution" in FORBIDDEN_FOR_AGENTS

    body = (REPO_ROOT / "core/ui/artifact_resolution.py").read_text(encoding="utf-8")
    assert "cross-investigation" in body.lower(), (
        "the cross-investigation rejection must stay documented at the point of resolution"
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
