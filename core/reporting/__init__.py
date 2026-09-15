"""Renderings of a finished Investigation: a timeline, and later a summary.

Not agents, and not Findings. A Finding is a claim about the incident; a
rendering is an ordering or a compression of the claims already made, and
putting one in the Findings list would be an agent reporting on the report.
Everything here is a pure function of the Investigation, deterministic, and
consults no model - the narrative postmortem Clio's manifest still promises
needs Delphi and somewhere to write to, and neither is here yet.

Phase: 5 - Proactive Flow
"""

from core.reporting.timeline import EntryKind, TimelineEntry, timeline

__all__ = ["EntryKind", "TimelineEntry", "timeline"]
