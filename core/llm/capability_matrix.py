"""What each model can actually do, as measured.

A cache of OBSERVATIONS, not a table of facts. A provider can change what sits
behind a stable model id without telling anyone, so every entry carries when it
was probed and goes stale on its own.

THREE STATES, NOT TWO
-----------------------
`ModelDescriptor.capabilities` is a list, so it can say *has* and *does not
have*. It cannot say **not checked**, and conflating the last two is what left
Hermes permanently unresolvable: it declares `JSON_MODE`, no model listed
`JSON_MODE` because nothing had probed, and the resolver read that absence as a
model that lacks it. A hard stop on a capability nobody looked for.

So a `Probed` record carries `present`, `absent` and - by omission - unprobed,
and `capabilities_for()` returns only what was *observed present*. The
difference is reported rather than smoothed: `unprobed_for()` exists so a caller
can say "no model is known to do this yet" instead of "no model can".

STALENESS IS A READ-TIME QUESTION
-----------------------------------
Like the approval gate's expiry, and for the same reason: a background sweep
makes the answer depend on whether the sweep ran. An entry older than
`STALE_AFTER` is reported as stale on read and its capabilities stop counting.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from core.contracts.llm import Capability

#: How long an observation is trusted. A week: long enough that probing is not
#: constant, short enough that a provider swapping the weights behind a stable
#: model id is noticed before it has answered a month of investigations.
STALE_AFTER = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class Probed:
    """One model, as observed at one moment.

    `present` and `absent` are separate sets rather than one list plus a
    negation, because a capability in neither is UNPROBED - and that is a third
    answer, not the absence of the first two.
    """

    provider_id: str
    model_id: str
    at: datetime
    present: frozenset[Capability] = frozenset()
    absent: frozenset[Capability] = frozenset()
    context_window: int = 0
    median_latency_ms: int | None = None
    #: Why the probe could not run, when it could not. An entry that failed is
    #: kept rather than dropped: "we tried and the provider refused" and "nobody
    #: has looked" are different, and only the first is worth retrying soon.
    error: str = ""

    @property
    def reachable(self) -> bool:
        return not self.error

    def unprobed(self) -> frozenset[Capability]:
        """Capabilities this record says nothing about."""
        return frozenset(Capability) - self.present - self.absent

    def is_stale(self, *, now: datetime, after: timedelta = STALE_AFTER) -> bool:
        return now - self.at >= after

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "at": self.at.isoformat(),
            "present": sorted(c.value for c in self.present),
            "absent": sorted(c.value for c in self.absent),
            "unprobed": sorted(c.value for c in self.unprobed()),
            "context_window": self.context_window,
            "median_latency_ms": self.median_latency_ms,
            "error": self.error,
        }


@dataclass
class CapabilityMatrix:
    """Probe results, keyed by (provider, model).

    In-process. Persisting it is a Phase 3 concern that arrives with the
    settings UI, and the shape it needs there is not one to guess at here - the
    same reasoning as the approval gate's store.
    """

    clock: Callable[[], datetime] = field(default_factory=lambda: _now)
    stale_after: timedelta = STALE_AFTER
    _entries: dict[tuple[str, str], Probed] = field(default_factory=dict)

    def record(self, probed: Probed) -> None:
        """Store an observation, replacing any earlier one for that model."""
        self._entries[(probed.provider_id, probed.model_id)] = probed

    def get(self, provider_id: str, model_id: str) -> Probed | None:
        return self._entries.get((provider_id, model_id))

    def fresh(self, provider_id: str, model_id: str) -> Probed | None:
        """The observation, or None if it is stale or missing.

        Stale and missing collapse here ON PURPOSE: both mean "nothing current
        is known", and a caller acting on a week-old capability is acting on a
        guess whether or not it is labelled one. `get()` is there for a UI that
        wants to show the stale value and its age.
        """
        entry = self._entries.get((provider_id, model_id))
        if entry is None or entry.is_stale(now=self.clock(), after=self.stale_after):
            return None
        return entry

    def capabilities_for(self, provider_id: str, model_id: str) -> frozenset[Capability]:
        """What this model was OBSERVED to do. Empty when nothing current is known.

        Never includes a capability that was merely not tested. An empty result
        from an unprobed model and an empty result from a model that failed
        every probe look the same here, which is why `unprobed_for` exists.
        """
        entry = self.fresh(provider_id, model_id)
        return entry.present if entry else frozenset()

    def unprobed_for(self, provider_id: str, model_id: str) -> frozenset[Capability]:
        """Capabilities nothing current says anything about.

        A caller refusing a model can then say "not known to support X" rather
        than "does not support X" - and those are different sentences to put in
        front of someone at three in the morning.
        """
        entry = self.fresh(provider_id, model_id)
        return frozenset(Capability) if entry is None else entry.unprobed()

    def stale(self) -> list[Probed]:
        """Everything worth re-probing, oldest first."""
        now = self.clock()
        old = [
            entry
            for entry in self._entries.values()
            if entry.is_stale(now=now, after=self.stale_after)
        ]
        old.sort(key=lambda entry: entry.at)
        return old

    def __len__(self) -> int:
        return len(self._entries)
