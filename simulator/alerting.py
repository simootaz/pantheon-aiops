"""How an alerting rule's timing relates to the compression factor.

One relationship, in one place, used by both the guard that checks the rules and
the gate that runs them. Writing it twice is how the two drift apart and the
guard starts certifying something the gate is not doing.

THE RELATIONSHIP
----------------
Prometheus evaluates `for:` clauses and range selectors in **wall** time. The
simulator advances **simulated** time `speed` times faster, so a fault lasting
D simulated seconds is only visible for `D / speed` wall seconds:

    range_window + for_hold  <  (D / speed) * BUDGET_FRACTION

Rearranged, that gives the fastest compression at which a rule can still fire::

    speed  <  D * BUDGET_FRACTION / (range_window + for_hold)

Both forms matter. `max_speed_for` is what the gate uses to pick a speed per
scenario - disk_pressure's fault runs for 216000 simulated seconds and does not
need the same slow clock as bad_deploy_5xx's 11400. `can_fire_at` is what the
guard uses to reject a rule whose window has outgrown its scenario.

WHY A BUDGET FRACTION
---------------------
Fitting exactly inside the window is not enough: Prometheus scrapes on its own
schedule, evaluates on another, and Alertmanager groups on a third. Half the
window leaves room for a rule to be *detected* rather than merely to coincide
with the last moment of a fault.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from simulator.runner import DEFAULT_TICK_SECONDS, max_honest_speed
from simulator.scenario import Scenario

#: Fraction of a fault's visible window a rule may consume. See above.
BUDGET_FRACTION = 0.5

#: Never compress below this, whatever the arithmetic allows. A scenario whose
#: fault lasts days would otherwise be run at a speed the pushgateway cannot be
#: scraped densely enough to sample.
MIN_SPEED = 60.0


def fault_seconds(scenario: Scenario) -> float:
    """How long the injected fault lasts, in simulated seconds."""
    last = max(float(phase.end_seconds) for phase in scenario.phases)
    first = min(float(phase.start_seconds) for phase in scenario.phases)
    return last - first


def max_speed_for(scenario: Scenario, rule_seconds: float) -> float:
    """The fastest compression at which a rule needing `rule_seconds` can fire.

    `rule_seconds` is the rule's longest range selector plus its `for:` hold -
    everything that has to elapse in wall time before it can go firing.
    """
    if rule_seconds <= 0:
        raise ValueError("a rule that needs no time at all cannot be timed")
    return fault_seconds(scenario) * BUDGET_FRACTION / rule_seconds


def can_fire_at(scenario: Scenario, rule_seconds: float, speed: float) -> bool:
    """Whether a rule has room to fire inside this scenario at this speed."""
    return speed <= max_speed_for(scenario, rule_seconds)


def gate_speed(scenario: Scenario, rule_seconds: float, tick_seconds: float) -> float:
    """A speed for running `scenario` that the rule can fire at and the runner can hold.

    Bounded three ways, and the tightest wins:

    * the rule must have room to fire (`max_speed_for`);
    * the runner must be able to deliver it (`max_honest_speed`), or the run
      silently takes longer than asked and every wall-clock assumption shifts;
    * `MIN_SPEED`, so a multi-day fault does not produce an hour-long gate.
    """
    achievable = max_honest_speed(tick_seconds)
    return max(MIN_SPEED, min(max_speed_for(scenario, rule_seconds), achievable))


def wall_seconds(scenario: Scenario, speed: float) -> float:
    """How long running the whole scenario takes at this compression."""
    return scenario.total_seconds / speed


__all__ = [
    "BUDGET_FRACTION",
    "DEFAULT_TICK_SECONDS",
    "MIN_SPEED",
    "can_fire_at",
    "fault_seconds",
    "gate_speed",
    "max_speed_for",
    "wall_seconds",
]
