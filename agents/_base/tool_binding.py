"""Binds the tools a manifest declares, and refuses every other one.

THE MANIFEST IS AN ALLOWLIST, NOT DOCUMENTATION
-----------------------------------------------
`tools:` in a manifest is the complete set of connector calls an agent may make.
Argus declares three `prometheus.*` tools; asking it for `loki.query` raises,
even though a Loki connector exists and is reachable.

That matters because the alternative - a manifest that merely *describes* what
an agent uses - is a document that drifts. An agent quietly reaching one tool
further is exactly the change nobody notices in review, and it is how a
read-only agent becomes a write-capable one.

Every call is counted, because `AgentBudget.max_tool_calls` is only a bound if
something is counting.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

#: A bound connector tool: name -> coroutine returning whatever it returns.
ToolCallable = Callable[..., Awaitable[Any]]


class ToolNotDeclared(PermissionError):
    """The agent asked for a tool its manifest does not list."""


class ToolNotBound(RuntimeError):
    """The tool is declared, but no connector provided an implementation.

    Deliberately a different exception from `ToolNotDeclared`. They are
    different failures - "you may not" versus "it is not here" - and collapsing
    them let a guard against the allowlist pass while the allowlist check was
    removed, because the unbound branch raised the same type.
    """


class ToolBudgetExceeded(RuntimeError):
    """The agent has spent its `max_tool_calls`."""


@dataclass(slots=True)
class BoundTools:
    """The toolset one agent is allowed, with the call budget attached.

    Constructed by `BaseAgent`; agents never build one, so an agent cannot widen
    its own allowlist by constructing a permissive toolset.
    """

    declared: frozenset[str]
    max_calls: int
    _implementations: dict[str, ToolCallable] = field(default_factory=dict)
    calls_made: int = 0
    called: list[str] = field(default_factory=list)

    def register(self, name: str, implementation: ToolCallable) -> None:
        """Make a declared tool callable. Undeclared names are refused here too.

        Registration is the other half of the allowlist: binding an undeclared
        implementation would make the check at call time pointless, because the
        tool would already be reachable by whoever holds the toolset.
        """
        if name not in self.declared:
            raise ToolNotDeclared(
                f"cannot bind {name!r}: the manifest declares {sorted(self.declared)}"
            )
        self._implementations[name] = implementation

    @property
    def calls_remaining(self) -> int:
        return max(self.max_calls - self.calls_made, 0)

    async def call(self, name: str, /, **kwargs: Any) -> Any:
        """Invoke a declared, bound tool, against the budget."""
        if name not in self.declared:
            raise ToolNotDeclared(
                f"{name!r} is not declared in this agent's manifest. "
                f"Declared: {sorted(self.declared)}. Add it to the manifest if the "
                "agent genuinely needs it - the manifest is the allowlist."
            )
        if name not in self._implementations:
            raise ToolNotBound(
                f"{name!r} is declared but no connector provided it. The connector "
                "is probably not running."
            )
        if self.calls_made >= self.max_calls:
            raise ToolBudgetExceeded(
                f"agent has made {self.calls_made} tool calls, its budget is "
                f"{self.max_calls}. Retrying will hit the same wall."
            )

        self.calls_made += 1
        self.called.append(name)
        return await self._implementations[name](**kwargs)
