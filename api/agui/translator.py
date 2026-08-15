"""Translate Pantheon's internal events into standard AG-UI events.

Internal events stay internal. `core/contracts/events.py` remains the bus
envelope; AG-UI is the *wire* format, and the translation happens here at the
edge. Conflating the two would make every internal change a protocol change.

THE SHARED STATE OBJECT IS THE INVESTIGATION
--------------------------------------------
AG-UI's state events carry one thing: the `Investigation`. A `StateSnapshot` at
`RunStarted`, `StateDelta` (RFC 6902 JSON Patch) for every change thereafter.

Naming it matters. "State" left undefined is how a second, competing state
object gets invented six months from now. It also makes replay trivial: the
snapshot plus the ordered patches reconstructs any run exactly, which is what
lets an operator scrub back through an incident.

MAPPING
-------
Domain event                    AG-UI event
----------------------------    --------------------------------------------
Investigation created           RunStarted + StateSnapshot(Investigation)
Investigation completed         RunFinished
Investigation failed            RunError
Agent dispatched / finished     StepStarted / StepFinished (stepName=codename)
Agent narration                 TextMessageStart/Content/End
Connector tool invoked          ToolCallStart/Args/End then ToolCallResult
Agent reasoning                 ReasoningStart .. ReasoningEnd
Finding produced                StateDelta   (findings are run state)
Verdict ready                   StateDelta
Delphi ResolutionRecord         StateDelta   (attached to the Investigation)
Cerberus AuditEntry             StateDelta   (attached to the Investigation)
Lease expired                   StateDelta (as a Finding) + an A2UI re-approval
                                surface when the grant merely expired
Approval required               A2UI surface, via a2ui_channel
Credential access requested     A2UI surface, via a2ui_channel
Break-glass invoked             Custom("pantheon.break_glass") + StateDelta

Only one domain concept uses `Custom`. The test for an exception is not "is it
ours?" but **"must the UI act the moment it arrives, and is that action not
itself an A2UI prompt?"** Break-glass alone passes: it revokes every live lease
across every run, so an open dashboard must react immediately rather than
render a new audit row. The Custom event is the *signal*; the AuditEntry patch
is the *record*.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

#: The only Custom event Pantheon defines. See the reasoning above.
CUSTOM_EVENTS = ("pantheon.break_glass",)

# TODO: Phase 4 - implement translate(event) -> Sequence[ag_ui.core.BaseEvent]
