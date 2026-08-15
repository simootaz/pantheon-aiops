"""Agentic UI contracts: the A2UI surface Pantheon supports.

Two protocols, cleanly divided - see docs/adr/0006-agentic-ui-protocols.md:

- **AG-UI** is the transport and runtime: streaming, tool-call visibility,
  shared-state sync, lifecycle, mid-run input.
- **A2UI** is the payload format for agent-generated UI travelling over it.

**AG-UI's own event types are NOT defined here.** They come from `ag_ui.core`
and are depended on, never redefined - restating a published schema is how the
two drift apart. This module defines only what is ours: which A2UI components
Pantheon renders, and the shapes our own edge needs.

THE ALLOWLIST IS A CONTRACT, DELIBERATELY
-----------------------------------------
`A2UIComponentType` generates into TypeScript, so the dashboard renderer
switches exhaustively over *the generated enum*. The allowlist, the renderer and
the capabilities we advertise are therefore one artifact and cannot drift apart.
An agent that emits anything outside it is rejected by the renderer, and
`tests/unit/test_agentic_ui.py` asserts that rejection.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel

#: A2UI specification version Pantheon implements. v1.0 is a release candidate
#: at the time of writing; the spec itself recommends v0.9.1 for production.
A2UI_VERSION = "v0.9.1"

#: Identifier for Pantheon's closed component catalog.
PANTHEON_CATALOG_ID = "pantheon.v1"


class A2UIComponentType(StrEnum):
    """The closed allowlist of A2UI components Pantheon will render.

    A subset of A2UI's basic catalog. Agent-generated UI is untrusted data, so
    the catalog is chosen for what it *cannot* be abused to do.

    Deliberately excluded, with reasons:

    - ``Image``, ``Video``, ``AudioPlayer`` - each fetches an agent-supplied URL.
      That outbound request is a data-exfiltration channel: an agent encodes
      what it learned into the URL and the browser delivers it. Excluded even
      though they are the most obviously useful components here.
    - ``Modal`` - an agent that can force a modal can overlay a convincing fake
      credential prompt. Credential requests travel one path only, through
      Cerberus.
    - ``Tabs``, ``Slider`` - no current use; the allowlist grows on demand and
      never speculatively.
    """

    # containers
    ROW = "Row"
    COLUMN = "Column"
    CARD = "Card"
    LIST = "List"
    # display
    TEXT = "Text"
    ICON = "Icon"
    DIVIDER = "Divider"
    # input
    TEXT_FIELD = "TextField"
    CHECK_BOX = "CheckBox"
    CHOICE_PICKER = "ChoicePicker"
    DATE_TIME_INPUT = "DateTimeInput"
    # interactive
    BUTTON = "Button"


class A2UISurfaceKind(StrEnum):
    """What a Pantheon-authored surface is for.

    Every surface Pantheon emits has a declared purpose, so the renderer can
    apply the right handling - notably that only APPROVAL and ACCESS_REQUEST may
    collect a decision, and both are bound to their existing backend paths.
    """

    APPROVAL = "approval"
    ACCESS_REQUEST = "access_request"
    REPORT = "report"
    NOTICE = "notice"


class A2UIAction(ContractModel):
    """A declared action on a component.

    A2UI carries either a server event or a local function call, both referenced
    **by name**. No executable code crosses the boundary in either direction.
    """

    event_name: str | None = Field(
        default=None, description="Server-dispatched action name, from the catalog."
    )
    function_call: str | None = Field(
        default=None, description="Client function name, from the catalog. Never code."
    )
    context: dict[str, Any] = Field(
        default_factory=dict, description="Values returned with the action."
    )


class A2UIComponent(ContractModel):
    """One component in a surface. Authored by an agent, rendered by the host.

    Note what is absent: no styling, no HTML, no script, and no identity fields.
    ``icon_url`` and ``agent_display_name`` live on A2UISurface and are set by
    the orchestrator, so an agent cannot present itself as another agent or as
    Pantheon itself.
    """

    id: str = Field(description="Unique within its surface.")
    component: A2UIComponentType = Field(description="Must be in the allowlist.")
    text: str | None = Field(default=None, description="Display text, where the type takes one.")
    label: str | None = Field(default=None, description="Input label, where the type takes one.")
    data_path: str | None = Field(
        default=None, description="RFC 6901 JSON Pointer into the surface data model."
    )
    children: list[str] = Field(default_factory=list, description="Child component ids.")
    action: A2UIAction | None = None


class A2UISurface(ContractModel):
    """A renderable surface, assembled by Pantheon rather than by an agent.

    Identity is set here, by the orchestrator, and never by the agent - A2UI
    calls this out explicitly as an anti-impersonation measure.
    """

    id: UUID
    kind: A2UISurfaceKind
    catalog_id: str = Field(default=PANTHEON_CATALOG_ID)
    a2ui_version: str = Field(default=A2UI_VERSION)
    root: str = Field(description="Id of the root component.")
    components: list[A2UIComponent] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(
        default_factory=dict, description="Initial values bound by JSON Pointer."
    )
    investigation_id: UUID | None = None

    # --- orchestrator-set identity. Agents never populate these. -----------
    agent_display_name: str = Field(
        default="Pantheon",
        description="Set by the orchestrator. An agent cannot claim another identity.",
    )
    icon_url: str | None = Field(
        default=None, description="Set by the orchestrator. Never agent-supplied."
    )


class A2UIClientCapabilities(ContractModel):
    """What the client can render, declared once at run start.

    A2UI carries this in A2A message metadata (`a2uiClientCapabilities`). AG-UI
    defines no analog, so this is **Pantheon convention, not specification**: the
    dashboard sends it in the AG-UI run input, and the agent is told what it may
    emit before it emits anything.

    `components` is generated from A2UIComponentType, so what we advertise is
    exactly what the renderer accepts - there is no second list to keep in step.
    """

    catalog_id: str = Field(default=PANTHEON_CATALOG_ID)
    a2ui_version: str = Field(default=A2UI_VERSION)
    components: list[A2UIComponentType] = Field(
        default_factory=lambda: list(A2UIComponentType),
        description="Every component the renderer accepts.",
    )


class UIActionResponse(ContractModel):
    """A user's response to an action, travelling back over AG-UI.

    Mirrors A2UI's client action message. Carries no decision authority of its
    own: an approval reaching the Approval Gate, or an access decision reaching
    Cerberus, is re-validated there against the request it claims to answer.
    """

    surface_id: UUID
    source_component_id: str
    action_name: str
    context: dict[str, Any] = Field(default_factory=dict)
    investigation_id: UUID | None = None


# TODO: Phase 4 - add per-component property schemas once the renderer exists
