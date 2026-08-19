"""Drives a scenario: baseline, then phases, pushing to the real stack.

The run loop is deliberately simple — tick, sample everything, push, sleep. The
interesting behaviour lives in the generators; a clever scheduler here would
make a failed run harder to explain.

Ticks are sized in *simulated* seconds and slept in *wall* seconds, so the same
scenario produces the same series at any speed. What changes with speed is how
many samples Prometheus captures, not what the curve looks like.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from core.config import get_settings
from simulator.clock import SimClock
from simulator.cluster import PODS, pods_for
from simulator.log_generator import LogGenerator, LogLine
from simulator.metrics_generator import MetricsGenerator
from simulator.pipeline_generator import PipelineGenerator
from simulator.scenario import Phase, Scenario

#: Simulated seconds per tick. Small enough that a phase boundary lands within
#: one tick of where the scenario says it does, large enough not to spend the
#: run pushing.
DEFAULT_TICK_SECONDS = 60.0

#: Never sleep longer than this between ticks, so Ctrl-C stays responsive and a
#: real-time run still pushes often enough for Prometheus to see it.
MAX_WALL_SLEEP = 2.0

#: A run delivering less than this fraction of its requested speed is reported
#: as falling behind. It is not an error - the data is still correct in
#: simulated time - but anything reasoning in wall time needs to know.
KEEP_UP_THRESHOLD = 0.8

#: Conservative wall cost of one tick: two HTTP round trips, whatever span of
#: simulated time the tick covers. Measured at ~102ms against a local Docker
#: stack and stable over hundreds of ticks; 0.12 leaves margin for a slower
#: machine. `tests/integration/test_simulator_data.py` measures it per machine
#: rather than trusting this - it is here so callers can pick a sane default.
NOMINAL_TICK_COST_SECONDS = 0.12


def max_honest_speed(tick_seconds: float = DEFAULT_TICK_SECONDS) -> float:
    """The fastest compression a given tick size can actually deliver.

    Asking for more is not an error, and the data stays correct in simulated
    time - but the run reports falling behind. A *default* above this line makes
    that warning fire on every ordinary invocation, which is how a real warning
    becomes background noise.
    """
    return tick_seconds / NOMINAL_TICK_COST_SECONDS


@dataclass(slots=True)
class RunReport:
    """What happened, for the CLI and for the empirical gate."""

    scenario: str
    speed: float
    ticks: int = 0
    metrics_pushes: int = 0
    log_lines: int = 0
    pipelines_sent: int = 0
    wall_seconds: float = 0.0
    simulated_seconds: float = 0.0
    fault_started_wall: float | None = None
    fault_ended_wall: float | None = None
    phases_entered: list[str] = field(default_factory=list)
    #: Simulated seconds actually delivered per wall second. This is the number
    #: that matters, and it is not always `speed`: pushing to Prometheus and
    #: Loki costs real time, so beyond some compression the run simply cannot
    #: keep up. Reporting it is what stops that being a silent failure.
    achieved_speed: float = 0.0
    #: Fraction of log lines emitted. See LogGenerator.sampling_ratio.
    log_sampling_ratio: float = 1.0

    @property
    def kept_up(self) -> bool:
        """Whether the run delivered close to the compression it was asked for."""
        return self.achieved_speed >= self.speed * KEEP_UP_THRESHOLD


class ScenarioRunner:
    """Runs one scenario against a live Prometheus, Loki and API."""

    def __init__(
        self,
        *,
        pushgateway: str | None = None,
        loki_url: str | None = None,
        webhook_url: str | None = None,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        settings = get_settings()
        self.metrics = MetricsGenerator(gateway=pushgateway or settings.pushgateway.host_port)
        self.logs = LogGenerator(loki_url=loki_url or settings.loki.base)
        self.pipelines = PipelineGenerator(webhook_url=webhook_url or settings.simulator.webhook)
        self.tick_seconds = tick_seconds
        self._on_event = on_event or (lambda _message: None)

    def _say(self, message: str) -> None:
        self._on_event(message)

    def run(self, scenario: Scenario, *, speed: float, send_pipelines: bool = True) -> RunReport:
        """Run baseline then phases, and report what was produced."""
        clock = SimClock(speed=speed)
        report = RunReport(scenario=scenario.name, speed=speed)
        started = time.monotonic()
        active: set[str] = set()

        with httpx.Client(timeout=10.0) as client:
            simulated = 0.0
            while simulated <= scenario.total_seconds:
                active_phases = scenario.active_at(simulated)
                phases = [running.phase for running in active_phases]
                names = {phase.name for phase in phases}

                for entering in sorted(names - active):
                    report.phases_entered.append(entering)
                    if report.fault_started_wall is None:
                        report.fault_started_wall = time.monotonic() - started
                    self._say(f"phase started: {entering}")
                for leaving in sorted(active - names):
                    self._say(f"phase ended: {leaving}")
                    report.fault_ended_wall = time.monotonic() - started
                active = names

                self.metrics.push(simulated, active_phases, self.tick_seconds, client)
                report.metrics_pushes += 1

                lines: list[LogLine] = []
                for pod in PODS:
                    lines.extend(self.logs.baseline_lines(pod, simulated, self.tick_seconds))
                for phase in phases:
                    for pattern in phase.logs:
                        for pod in pods_for(phase.target):
                            lines.extend(
                                self.logs.phase_lines(
                                    pod,
                                    pattern.template,
                                    pattern.per_minute,
                                    pattern.level,
                                    self.tick_seconds,
                                    simulated,
                                )
                            )
                report.log_lines += self.logs.push(lines, client)

                if send_pipelines:
                    report.pipelines_sent += self._maybe_send_pipeline(client, scenario, phases)

                report.ticks += 1
                simulated += self.tick_seconds
                # Pace against an absolute schedule, not tick by tick. See
                # _sleep_until: per-tick sleeps accumulate every overshoot.
                self._sleep_until(started + clock.wall_for(simulated))

        report.wall_seconds = time.monotonic() - started
        report.simulated_seconds = simulated
        report.log_sampling_ratio = self.logs.sampling_ratio(self.tick_seconds)
        report.achieved_speed = simulated / report.wall_seconds if report.wall_seconds > 0 else 0.0
        if not report.kept_up:
            self._say(
                f"fell behind: asked for {speed:.0f}x, delivered "
                f"{report.achieved_speed:.0f}x. Pushing costs wall time, so this "
                f"tick size ({self.tick_seconds:.0f}s simulated) cannot go faster. "
                "Raise tick_seconds or lower --speed."
            )
        return report

    def _maybe_send_pipeline(
        self, client: httpx.Client, scenario: Scenario, phases: list[Phase]
    ) -> int:
        """Send a pipeline event when a phase asks for one.

        A scenario signals this by naming a `test_flake` or deployment log
        pattern; rather than invent a second vocabulary, the pipeline follows
        the same phases the metrics do.
        """
        sent = 0
        for phase in phases:
            templates = {pattern.template for pattern in phase.logs}
            if "test_flake" in templates:
                self.pipelines.send_pipeline(client, status="failed", failed_jobs=["integration"])
                sent += 1
            elif phase.name.startswith("deploy"):
                self.pipelines.send_pipeline(client, status="success", ref="main")
                sent += 1
        return sent

    @staticmethod
    def _sleep_until(deadline: float) -> None:
        """Sleep to an absolute deadline rather than for a fixed duration.

        Sleeping `tick_seconds / speed` on each iteration looks equivalent and
        is not: `time.sleep` may only overshoot, never undershoot, and the OS
        timer granularity is around 16ms on Windows. A 271ms sleep lands at
        roughly 313ms, and nothing ever gives that back — so the error compounds
        once per tick.

        Measured: over 554 ticks it turned a requested 2880x into 1880x, while
        the actual work per tick was a steady 102ms and had plenty of room. The
        run was not too slow; it was sleeping too long, 554 times.

        Pacing to a schedule absorbs each overshoot in the next sleep. If a tick
        genuinely runs past its deadline the loop simply stops sleeping, and
        `achieved_speed` reports the shortfall.
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, MAX_WALL_SLEEP))

    def baseline(self, *, speed: float, simulated_seconds: float) -> RunReport:
        """Emit only normal behaviour, for training or for inspecting the curve."""
        from core.contracts.root_cause import RootCauseCategory
        from simulator.scenario import ExpectedRootCause, Phase
        from simulator.scenario import Scenario as ScenarioModel

        quiet = ScenarioModel(
            name="baseline",
            title="Baseline only",
            description="Normal behaviour with no fault injected.",
            baseline_seconds=simulated_seconds,
            phases=[
                Phase(
                    name="none",
                    start_seconds=0.0,
                    duration_seconds=1.0,
                    target="*",
                    note="No deviation; present because a scenario needs a phase.",
                )
            ],
            expected_root_cause=ExpectedRootCause(
                category=RootCauseCategory.UNKNOWN,
                subject="none",
                statement="Nothing is wrong; this is the reference behaviour.",
            ),
        )
        return self.run(quiet, speed=speed, send_pipelines=False)
