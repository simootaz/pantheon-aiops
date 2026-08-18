"""Argus - detects metric anomalies and correlates them into candidate Findings.

Phase 1 detection is deliberately **statistical only**. No LLM is involved, and
none is needed: `AgentManifest` has no model-requirements field, and
`Finding.rationale` is optional, so a templated title plus real Evidence is a
complete, valid claim. Delphi arrives at Phase 2 to narrate `rationale` and to
propose hypotheses, which is a different job from detecting.

The method and its threshold are stated rather than tuned in private, the same
way `tests/integration/test_simulator_data.py` states them: a point is anomalous
when it exceeds the window's own baseline by `Z_THRESHOLD` standard deviations
and stays there for `SUSTAIN` consecutive samples. Sustain is what separates an
incident from a single noisy scrape.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from agents._base.base_agent import AgentContext, BaseAgent
from core.contracts.finding import Finding

#: Standard deviations above the window baseline before a point is anomalous.
Z_THRESHOLD = 3.0
#: Consecutive samples that must exceed it. One sample is noise, not an incident.
SUSTAIN = 3


class Argus(BaseAgent):
    """The first real agent, and the template the other nine follow."""

    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Query Prometheus and report sustained departures from baseline.

        Returns `[]` when the window is clean - that is a result, not a failure -
        and raises `AgentDegraded` when Prometheus cannot be reached, so the
        runtime turns it into a DEGRADED Finding.
        """
        raise NotImplementedError(
            "Argus detection lands on feature/argus; the runtime it plugs into is here."
        )


# TODO: Phase 1 - implement detection on feature/argus, gated on a stated
# false-positive bound against a baseline-only simulator run
