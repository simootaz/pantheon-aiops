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
from core.orchestrator.dispatcher import AGENTS, AgentNotDispatchable, register
from core.orchestrator.planner import IMPLEMENTED, NoAgentForDomain, build
from core.orchestrator.router import DEFAULT_LOOKBACK, get, investigate


def register_implemented() -> None:
    """Make every implemented agent dispatchable.

    An explicit call rather than import-time magic: a registry populated as a
    side effect of importing is one that behaves differently depending on what
    else has been imported, and the failure shows up at dispatch.
    """
    from agents.anomaly.agent import Argus
    from agents.log_clustering.agent import Lethe
    from agents.nl_query.agent import Hermes

    register("argus", Argus)
    register("lethe", Lethe)
    register("hermes", Hermes)

    # Aegis and Hephaestus are implemented and NOT registered, deliberately.
    #
    # Both read their subject off `ctx.params` - a pull request, a CI run - and
    # `dispatcher.py` populates none: it builds an AgentContext from a window
    # and a trigger. Registering them would put two agents in a plan that
    # degrade on every dispatch with "no run was named", which reads as a broken
    # agent rather than as a missing route.
    #
    # `test_nothing_is_registered_that_the_planner_will_never_name` refused the
    # registration when it was attempted, which is what that guard is for. The
    # route - classifier, planner and params from the webhook payload - is the
    # work that makes this line correct, and it is its own change.


__all__ = [
    "AGENTS",
    "DEFAULT_LOOKBACK",
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
