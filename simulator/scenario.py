"""Scenario definitions: phased fault injection with declared ground truth.

A scenario says what goes wrong, to which pods, when, and — crucially — **what
the right answer is**. `expected_root_cause` draws its category from
`RootCauseCategory`, the same closed vocabulary a `Verdict` uses, so an agent's
conclusion can be compared to ground truth by equality rather than by matching
prose. `tests/unit/test_contracts.py` fails the build if a scenario names a
category that does not exist.

Scenarios describe **deviations from baseline**, never absolute values. A phase
that sets memory to a fixed number would erase the seasonality and noise the
baseline exists to provide, and an anomaly detector trained on the result would
be learning from a step function.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from core.contracts.base import ContractModel
from core.contracts.root_cause import RootCauseCategory

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


class MetricName(StrEnum):
    """Metrics a scenario may perturb. Closed, so a typo is a load error."""

    CPU = "cpu"
    MEMORY = "memory"
    REQUEST_RATE = "request_rate"
    ERROR_RATE = "error_rate"
    LATENCY = "latency"
    RESTARTS = "restarts"
    DISK_USED = "disk_used"


class Shape(StrEnum):
    """How a deviation develops over its phase.

    The shape matters as much as the magnitude: a leak that ramps and a crash
    that steps look identical if you only compare the endpoints, and telling
    them apart is exactly the job.
    """

    STEP = "step"
    RAMP = "ramp"
    SPIKE = "spike"
    SAWTOOTH = "sawtooth"


class Deviation(ContractModel):
    """One metric pushed away from its baseline, by a multiplier or an offset.

    Multiplicative by default because baselines differ per pod: `factor: 3.0`
    means "three times whatever this pod normally does", which stays meaningful
    across a busy checkout pod and a quiet notifier.
    """

    metric: MetricName
    factor: float | None = Field(
        default=None, gt=0.0, description="Multiply the baseline. 3.0 means triple."
    )
    offset: float | None = Field(
        default=None, description="Add to the baseline, in the metric's own unit."
    )
    shape: Shape = Shape.RAMP

    @model_validator(mode="after")
    def _one_of_factor_or_offset(self) -> Deviation:
        if (self.factor is None) == (self.offset is None):
            raise ValueError(
                f"deviation on {self.metric.value} must set exactly one of factor or offset"
            )
        return self


class LogPattern(ContractModel):
    """A log template a phase starts emitting, and how often."""

    template: str = Field(description="Key into simulator.log_generator.TEMPLATES.")
    per_minute: float = Field(default=6.0, ge=0.0, description="Simulated occurrences per minute.")
    level: str = Field(default="error")


class Phase(ContractModel):
    """A window of simulated time during which deviations apply."""

    name: str
    start_seconds: float = Field(ge=0.0, description="Simulated seconds from scenario start.")
    duration_seconds: float = Field(gt=0.0)
    target: str = Field(description="Service, node, pod name, or '*'.")
    deviations: list[Deviation] = Field(default_factory=list)
    logs: list[LogPattern] = Field(default_factory=list)
    note: str = Field(default="", description="What a human watching should see.")

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds


class ExpectedRootCause(ContractModel):
    """The ground truth an agent is scored against.

    Structured rather than prose. Scoring "the connection pool was exhausted"
    against "pool exhaustion" by string comparison is worthless, which is why
    `category` comes from the contract vocabulary.
    """

    category: RootCauseCategory
    subject: str = Field(description="What is at fault, e.g. 'checkout'.")
    statement: str = Field(description="The answer in words, for a human reading a report.")
    supporting_signals: list[str] = Field(
        default_factory=list,
        description="Signals an agent should have cited. Used to score reasoning, "
        "not only the conclusion.",
    )


@dataclass(frozen=True)
class ActivePhase:
    """A phase that is running, and how far through it we are.

    Deliberately not two separate returns. A caller that receives a phase and
    computes its own progress is free to choose a different time origin, which
    is exactly the defect this type exists to make unrepresentable.
    """

    phase: Phase
    progress: float


class Scenario(ContractModel):
    """A complete fault injection with its answer key."""

    name: str
    title: str
    description: str
    baseline_seconds: float = Field(
        default=172_800.0,
        gt=0.0,
        description="Simulated seconds of normal behaviour before the first phase. "
        "Two days by default, so a detector has more than one cycle to learn from.",
    )
    phases: list[Phase] = Field(min_length=1)
    expected_root_cause: ExpectedRootCause

    @model_validator(mode="after")
    def _phases_are_ordered_and_named_uniquely(self) -> Scenario:
        names = [phase.name for phase in self.phases]
        if len(names) != len(set(names)):
            raise ValueError(f"scenario {self.name} has duplicate phase names: {names}")

        starts = [phase.start_seconds for phase in self.phases]
        if starts != sorted(starts):
            raise ValueError(
                f"scenario {self.name} lists phases out of order; timing is read by "
                "humans as well as machines"
            )
        return self

    @property
    def total_seconds(self) -> float:
        """Simulated duration of the whole run, baseline included."""
        return self.baseline_seconds + max(phase.end_seconds for phase in self.phases)

    def active_at(self, simulated_seconds: float) -> list[ActivePhase]:
        """Every phase active now, each with how far through it we are.

        Activity and progress share one time origin **by construction**, which
        is the whole reason this returns a pair rather than a phase.

        They used to be computed in three places against two different origins:
        this method subtracted `baseline_seconds`, while `MetricsGenerator`
        computed `(simulated_seconds - phase.start_seconds) / duration` from
        absolute time, in two separate methods. Absolute time is always at
        least `baseline_seconds`, so progress never fell inside [0, 1] - it ran
        2.18 to 3.18 through a phase and clamped to 1.0 throughout.

        The visible cost: `ramp` was indistinguishable from `step`, and `spike`
        and `sawtooth` were **inert**, because their shape factors are 0.0 at
        progress 1.0. Three of the four shapes did not do what they said.
        """
        offset = simulated_seconds - self.baseline_seconds
        return [
            ActivePhase(
                phase=phase,
                progress=(offset - phase.start_seconds) / phase.duration_seconds,
            )
            for phase in self.phases
            if phase.start_seconds <= offset < phase.end_seconds
        ]


def load(name: str) -> Scenario:
    """Load one scenario by name, validating it fully."""
    path = SCENARIO_DIR / f"{name}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(s.stem for s in SCENARIO_DIR.glob("*.yaml")))
        raise FileNotFoundError(f"no scenario named {name!r}. available: {available}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario.model_validate(raw)


def load_all() -> list[Scenario]:
    """Every scenario, for `pantheon-sim list` and for the guards."""
    return [load(path.stem) for path in sorted(SCENARIO_DIR.glob("*.yaml"))]
