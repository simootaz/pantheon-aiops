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
#: The tick the empirical alert gate runs at, and therefore the tick every
#: statement about speeds and headroom must be made against.
#:
#: It lives here rather than in the gate because a guard that computed headroom
#: at `DEFAULT_TICK_SECONDS` (60s) was measuring a configuration nothing runs:
#: at that tick `max_honest_speed` caps every scenario at 500x, which hands
#: each of them eight intervals of headroom and makes the guard unfailable. The
#: gate runs at 300s, where the caps do not bind and the bounds actually decide.
GATE_TICK_SECONDS = 300.0

#: Prometheus evaluates the sim rules every 5s (`interval` in rules.sim.yml).
#: Headroom has to be counted in these, not as a fraction: a rule needs the
#: signal held past its `for:` across whole evaluations, and evaluations land
#: on a fixed grid the fault does not align with.
EVALUATION_INTERVAL_SECONDS = 5.0

#: Evaluation intervals of headroom a rule must have beyond what it needs.
#:
#: Derived, in two steps, and the second is the one that is easy to miss.
#:
#: **What firing requires.** A `for: F` completes when an evaluation sees the
#: condition continuously true for F. The first evaluation after the signal
#: crosses can be up to one interval late, so the signal must stay above the
#: threshold for `F + E` to guarantee it, and `F + 2E` leaves an interval of
#: safety. That is a constraint on **time above threshold**, not on how long
#: the fault is visible.
#:
#: **Why those are not the same number.** The signal is above its threshold for
#: only part of the fault - it ramps in and out. Measured, that fraction runs
#: from 25% (`disk_pressure`) to 95% (`bad_deploy_5xx`), so the visible window
#: needed to buy `F + 2E` of sustain ranges from 2.3 to 14.2 intervals of
#: headroom depending on the scenario. A single number on the visible window
#: cannot express the requirement exactly; it can only be set high enough to
#: cover the worst measured case.
#:
#: Six covers all five with margin: `noisy_neighbor` needs 4.8 and
#: `flaky_test_storm` 5.0, and both then sustain ~23s against a 20s
#: requirement. It replaces a first attempt at three, which was derived from
#: alignment alone and silently assumed the signal is above threshold for the
#: whole fault - true of none of them.
#:
#: The empirical gate remains the proof. This bound makes it hard to pass by
#: luck; it does not make passing certain, and nothing here should be read as
#: if it did.
MIN_HEADROOM_INTERVALS = 6.0

#: The older bound, kept as the second of two. It says a rule may use half the
#: visible fault - which for a 10s rule *is* exactly two evaluation intervals
#: of headroom, the coin-flip case, and that is what it got wrong. But it is
#: stricter than the interval floor wherever `rule_seconds` is large, so both
#: are applied and the tighter wins.
#:
#: The lesson is not that a ratio is wrong. It is that a ratio and a fixed-step
#: margin constrain different things, and a rule evaluated on a grid needs
#: both: at 40s visible the fraction grants four intervals, at 20s it grants
#: two, and only one of those works.
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
    everything that has to elapse in wall time before it can go firing - and the
    fault must stay visible for that **plus `MIN_HEADROOM_INTERVALS` evaluation
    intervals**, not merely longer than it.
    """
    if rule_seconds <= 0:
        raise ValueError("a rule that needs no time at all cannot be timed")
    fault = fault_seconds(scenario)
    # Two bounds, and the tighter wins. The interval floor is a MINIMUM, not a
    # target: applied alone it made bad_deploy_5xx *faster* (285x to 326x) and
    # cut its headroom from four intervals to three, loosening a rule that was
    # comfortable in order to tighten one that was not.
    by_intervals = fault / (rule_seconds + MIN_HEADROOM_INTERVALS * EVALUATION_INTERVAL_SECONDS)
    by_fraction = fault * BUDGET_FRACTION / rule_seconds
    return min(by_intervals, by_fraction)


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
    "EVALUATION_INTERVAL_SECONDS",
    "GATE_TICK_SECONDS",
    "MIN_HEADROOM_INTERVALS",
    "MIN_SPEED",
    "can_fire_at",
    "fault_seconds",
    "gate_speed",
    "max_speed_for",
    "wall_seconds",
]
