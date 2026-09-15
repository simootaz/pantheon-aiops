"""Zeus: routes triggers, plans, dispatches to agents and aggregates results.

The entrypoint is `investigate`. Everything else here is one stage of it, kept
separate because a classifier that can only be tested by running a dispatcher
is a classifier nobody tests.

WHAT ZEUS DOES NOT DO YET
-------------------------
It plans one step, because one agent is implemented. It proposes no hypotheses,
because nothing ranks candidate causes - see `aggregator.py`. It runs the plan
in a loop rather than a workflow engine, because a single step with no waits
needs no durable execution - see `dispatcher.py` for what would force that.

Phase: 2 - Orchestrator & Investigation Flow
"""

from core.orchestrator.aggregator import aggregate
from core.orchestrator.classifier import Classification, classify
from core.orchestrator.dispatcher import (
    AGENTS,
    IMPLEMENTATIONS,
    AgentNotDispatchable,
    register,
)
from core.orchestrator.planner import IMPLEMENTED, NoAgentForDomain, build
from core.orchestrator.router import DEFAULT_LOOKBACK, get, investigate


def register_implemented() -> None:
    """Make every implemented agent dispatchable.

    An explicit call rather than import-time magic: a registry populated as a
    side effect of importing is one that behaves differently depending on what
    else has been imported, and the failure shows up at dispatch.
    """
    from agents.anomaly.agent import Argus
    from agents.capacity.agent import Moira
    from agents.ci_triage.agent import Hephaestus
    from agents.dora.agent import Themis
    from agents.knowledge.agent import Mnemosyne
    from agents.log_clustering.agent import Lethe
    from agents.manifest_review.agent import Aegis
    from agents.nl_query.agent import Hermes

    register("argus", Argus)
    register("lethe", Lethe)
    register("hermes", Hermes)
    # Reachable as of the webhook route: `classifier.subject_of` puts the pull
    # request or the CI run on `ctx.params`, so these two are pointed at
    # something rather than degrading with "no run was named". Registering them
    # before that existed was refused by
    # `test_nothing_is_registered_that_the_planner_will_never_name`.
    register("aegis", Aegis)
    register("hephaestus", Hephaestus)
    # Reachable through ALERT_DOMAINS: every alert is also a capacity question.
    register("moira", Moira)
    # And a memory question. Its one tool is provided by the dispatcher rather
    # than a connector, because it closes over the investigation store.
    register("mnemosyne", Mnemosyne)

    # Reachable through a scheduled job - `api/routers/schedules.py` - which is
    # what a delivery measurement belongs on. This was `dispatchable=False` with
    # a comment saying nothing could schedule anything until Temporal landed;
    # `dispatcher.py` names what would force Temporal, and a CronJob firing a
    # trigger is not on the list.
    register("themis", Themis)


__all__ = [
    "AGENTS",
    "DEFAULT_LOOKBACK",
    "IMPLEMENTATIONS",
    "IMPLEMENTED",
    "AgentNotDispatchable",
    "Classification",
    "NoAgentForDomain",
    "aggregate",
    "build",
    "classify",
    "get",
    "investigate",
    "register",
    "register_implemented",
]
