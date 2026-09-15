"""A2UI surface construction.

Pantheon assembles surfaces here; agents describe intent, and this package turns
that into components drawn strictly from the allowlist in
core.contracts.ui.A2UIComponentType.

Identity fields on A2UISurface are set by the orchestrator, never by an agent.

ALLOWED IMPORT SURFACE
----------------------
Code under ``agents/`` may import the surface builders, but **not**:

    core.ui.artifact_resolution  - turns an ArtifactRef into a fetchable signed
                                   URL. An agent that could resolve could also
                                   read the result, which is the exfiltration
                                   path ArtifactRef exists to close.

The same boundary as ``core.cerberus.redemption``, for the same reason: the
agent holds a reference, the server holds the capability. Enforced at the import
graph by tests/unit/test_credential_safety.py.

`artifact_resolution` is deliberately NOT re-exported below - but be clear about
what that buys. Importing the submodule anywhere binds it as an attribute of
this package, so `core.ui.artifact_resolution` is reachable whatever `__all__`
says. A test asserting otherwise was written and failed, which is how this
paragraph got written.

The boundary is the IMPORT GRAPH, enforced by
`tests/unit/test_credential_safety.py`. `__all__` buys the narrower thing: no
name from the resolver arrives through `from core.ui import ...`, so reaching it
has to be deliberate and is therefore visible to the guard.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from core.ui.access_request import access_surface, renewal_surface
from core.ui.approval import approval_surface

__all__ = ["access_surface", "approval_surface", "renewal_surface"]
