"""Simulated time, and the compression factor that makes a day fit in a test.

WHY COMPRESSION EXISTS
----------------------
The simulator pushes metrics through a Prometheus pushgateway, which **discards
timestamps by design**: it holds the last value pushed, and Prometheus stamps it
at scrape time. A baseline curve therefore only exists in elapsed wall time — it
cannot be backfilled.

So to show a daily cycle in a test that finishes, a simulated day is compressed
into wall seconds. `speed` is the compression factor: at `speed=1` a simulated
second is a wall second, and at `speed=4320` a simulated day passes in twenty
wall seconds.

Compression is a **parameter, not a constant**, and real time is always
available. A scenario that only exists at 4320x is one nobody can watch
happen, and watching it happen is how you notice it looks wrong.

THE LIMIT, STATED
-----------------
Compression buys a *shape*, not *history*. Prometheus still records the samples
at real timestamps seconds apart, so a compressed week is seconds of stored data
however fast it is generated. Anything needing genuine history — Moira
forecasting thirty days — needs `remote_write` with explicit timestamps instead.
Tracked in ROADMAP.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

SECONDS_PER_DAY = 86_400.0

#: Real time. A simulated second takes a wall second.
REALTIME = 1.0

#: A simulated day in roughly twenty wall seconds — the default for tests.
FAST = 4_320.0


@dataclass(slots=True)
class SimClock:
    """Maps wall time onto simulated time at a fixed compression factor."""

    speed: float = REALTIME
    started_at: float = field(default_factory=time.monotonic)
    origin: float = 0.0

    def __post_init__(self) -> None:
        if self.speed <= 0:
            raise ValueError(f"speed must be positive, got {self.speed}")

    @property
    def realtime(self) -> bool:
        """True when no compression is applied."""
        return self.speed == REALTIME

    def elapsed_wall(self) -> float:
        """Wall seconds since the clock started."""
        return time.monotonic() - self.started_at

    def now(self) -> float:
        """Simulated seconds since the scenario began."""
        return self.origin + self.elapsed_wall() * self.speed

    def wall_for(self, simulated_seconds: float) -> float:
        """How long to wait, in wall seconds, for a simulated duration."""
        return simulated_seconds / self.speed

    def time_of_day(self) -> float:
        """Position within the simulated day, in seconds from midnight.

        This is what drives seasonality: the baseline reads its diurnal phase
        from here, so the same generator produces a night trough and a midday
        peak without knowing anything about compression.
        """
        return self.now() % SECONDS_PER_DAY

    def day_fraction(self) -> float:
        """Position within the simulated day, 0.0 to 1.0."""
        return self.time_of_day() / SECONDS_PER_DAY


def describe(speed: float) -> str:
    """A human sentence for the CLI, so the compression is never a mystery."""
    if speed == REALTIME:
        return "real time (1 simulated second per wall second)"
    day_seconds = SECONDS_PER_DAY / speed
    if day_seconds < 90:
        return f"{speed:g}x - one simulated day every {day_seconds:.0f} wall seconds"
    return f"{speed:g}x - one simulated day every {day_seconds / 60:.1f} wall minutes"
