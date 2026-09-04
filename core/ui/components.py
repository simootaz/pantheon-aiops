"""Builders restricted to the allowlist.

Named components.py rather than catalog.py: core/llm/catalog.py already exists,
and two catalogs in one tree invites mis-greps - the same reasoning that renamed
registry.py to catalog.py and resolver.py to redemption.py.

Every builder returns an A2UIComponent whose type is an A2UIComponentType
member, so an unrenderable component cannot be constructed in the first place.

WHY THERE IS A BUILDER PER TYPE RATHER THAN ONE GENERIC ONE
-------------------------------------------------------------
`A2UIComponent(id=..., component=...)` already refuses a type outside the enum,
so a single generic builder would be no less safe. What it would not do is stop
a caller putting a `label` on a Divider or an `action` on a Text - fields the
contract allows because some component needs each of them, and no component
needs all of them.

One builder per type means the signature says which fields that type takes.
A Divider builder has no `text` parameter, so a Divider carrying text is not
something a caller can express by accident.

`image` IS THE ONE WORTH READING TWICE
----------------------------------------
It takes an `ArtifactRef` and there is deliberately no URL parameter. An agent
cannot express an arbitrary destination, so there is nothing to filter - and
`core/ui/artifact_resolution.py` is the only thing that turns the reference into
something fetchable, server-side.

A builder accepting a URL "just for internal use" would put the exfiltration
path back, because the component travels to a browser either way.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from core.contracts.ui import (
    A2UIAction,
    A2UIComponent,
    A2UIComponentType,
    ArtifactRef,
)


def row(component_id: str, *children: str) -> A2UIComponent:
    """A horizontal container."""
    return A2UIComponent(id=component_id, component=A2UIComponentType.ROW, children=list(children))


def column(component_id: str, *children: str) -> A2UIComponent:
    """A vertical container."""
    return A2UIComponent(
        id=component_id, component=A2UIComponentType.COLUMN, children=list(children)
    )


def card(component_id: str, *children: str) -> A2UIComponent:
    """A bounded region. What every Pantheon prompt is rooted in."""
    return A2UIComponent(id=component_id, component=A2UIComponentType.CARD, children=list(children))


def listing(component_id: str, *children: str) -> A2UIComponent:
    """A list container.

    Not named `list`: shadowing a builtin in a module every surface imports is
    how a `list(...)` three files away starts building components.
    """
    return A2UIComponent(id=component_id, component=A2UIComponentType.LIST, children=list(children))


def text(component_id: str, value: str) -> A2UIComponent:
    """Display text. No action, because a Text that could act is a hidden button."""
    return A2UIComponent(id=component_id, component=A2UIComponentType.TEXT, text=value)


def image(component_id: str, artifact: ArtifactRef) -> A2UIComponent:
    """An image, by REFERENCE.

    There is no URL parameter and there will not be one. See the module
    docstring: the reference is what an agent may express, and resolving it is
    `core/ui/artifact_resolution.py`'s job, server-side.
    """
    return A2UIComponent(id=component_id, component=A2UIComponentType.IMAGE, artifact_ref=artifact)


def icon(component_id: str, name: str) -> A2UIComponent:
    """A named icon. `text` carries the name, which is what the catalog keys on."""
    return A2UIComponent(id=component_id, component=A2UIComponentType.ICON, text=name)


def divider(component_id: str) -> A2UIComponent:
    """A rule. Takes nothing, because it displays nothing."""
    return A2UIComponent(id=component_id, component=A2UIComponentType.DIVIDER)


def text_field(component_id: str, label: str, *, data_path: str) -> A2UIComponent:
    """A free-text input, bound to a path in the surface's data model.

    `data_path` is required rather than optional. An input with nowhere to write
    collects a value the surface then discards, and it looks identical to one
    that works right up until somebody types in it.
    """
    return A2UIComponent(
        id=component_id,
        component=A2UIComponentType.TEXT_FIELD,
        label=label,
        data_path=data_path,
    )


def check_box(component_id: str, label: str, *, data_path: str) -> A2UIComponent:
    return A2UIComponent(
        id=component_id,
        component=A2UIComponentType.CHECK_BOX,
        label=label,
        data_path=data_path,
    )


def choice_picker(component_id: str, label: str, *, data_path: str) -> A2UIComponent:
    return A2UIComponent(
        id=component_id,
        component=A2UIComponentType.CHOICE_PICKER,
        label=label,
        data_path=data_path,
    )


def date_time_input(component_id: str, label: str, *, data_path: str) -> A2UIComponent:
    return A2UIComponent(
        id=component_id,
        component=A2UIComponentType.DATE_TIME_INPUT,
        label=label,
        data_path=data_path,
    )


def button(
    component_id: str,
    label: str,
    *,
    action: str,
    context: dict[str, str] | None = None,
) -> A2UIComponent:
    """The only component that can act, and the action is required.

    A Button with no action is a control that does nothing when pressed, which
    on an approval prompt is indistinguishable from one whose answer was lost.
    """
    return A2UIComponent(
        id=component_id,
        component=A2UIComponentType.BUTTON,
        label=label,
        action=A2UIAction(event_name=action, context=dict(context or {})),
    )
