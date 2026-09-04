"""A TTL cache for model completions, and for nothing else.

WHY NOT CONNECTOR RESPONSES
-----------------------------
A cached Prometheus read answers with the past. During an incident that is
exactly when the difference matters, and the failure is silent: an agent reasons
correctly over a number that was true five minutes ago and reaches a conclusion
nobody can reproduce. The saving would be small anyway - a connector call is one
HTTP round trip on the local network, while a model call is money and seconds.

WHY A COMPLETION IS SAFE TO CACHE WHEN A METRIC READ IS NOT
-------------------------------------------------------------
The key is the **whole request**: model, prompt, system, token ceiling and JSON
mode. Agents that consult Delphi put the data they are reasoning about *in the
prompt* - Hermes embeds the query result, Lethe would embed the template set. So
if the data changed, the prompt changed, and the key changed. A hit means the
identical question was asked of the identical model about the identical data.

That is a property of how callers build prompts, not a guarantee this module can
make. A caller that put a bare question in the prompt and the data somewhere else
would break it silently, which is why it is asserted in the tests and stated in
ADR 0008 rather than left as an assumption.

A HIT IS NOT A PAID CALL
--------------------------
`hits` and `misses` are counted separately and a hit is reported as such, so a
caller can record zero cost against it. Replaying the original cost would make
"what did this investigation spend" climb while no money moved.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

#: How long a completion stays usable. Short: the value is in a retry or a
#: repeated sub-question inside one investigation, not across an afternoon. A
#: long TTL would start answering a *later* investigation with an earlier one's
#: reasoning, which is the connector hazard arriving by another route.
DEFAULT_TTL_SECONDS = 900.0

#: Entries kept before the oldest is evicted. A ceiling rather than unbounded
#: growth: this lives in the API process, and a cache that grows with traffic is
#: a leak with a friendly name.
DEFAULT_MAX_ENTRIES = 512


class Clock(Protocol):
    """Monotonic seconds. Injected so expiry is testable without sleeping."""

    def __call__(self) -> float: ...


@dataclass(frozen=True)
class CacheKey:
    """Everything that determines a completion.

    A frozen dataclass rather than a tuple so a field cannot be added to the
    request and forgotten here - the constructor call fails instead of silently
    returning a completion produced under different parameters.
    """

    model_id: str
    prompt: str
    system: str | None
    #: The provider's per-call ceiling. Named `token_ceiling` rather than
    #: `max_tokens` on purpose: `AgentBudget.max_tokens` is a RUN budget that
    #: nothing may read until Delphi provides a meter, and
    #: `test_nothing_reads_the_token_budget_yet` enforces that by matching the
    #: attribute name. Two different concepts sharing a spelling is how a guard
    #: over one starts firing on the other - and how a reader conflates them.
    token_ceiling: int
    json_mode: bool

    def digest(self) -> str:
        """A stable hash of the request.

        Hashed rather than stored whole: a prompt can carry a redacted secret or
        a customer's data, and a cache keyed on the plaintext puts it in a
        process dump. The digest is enough to match on and useless to read.
        """
        body = json.dumps(
            {
                "model_id": self.model_id,
                "prompt": self.prompt,
                "system": self.system,
                "token_ceiling": self.token_ceiling,
                "json_mode": self.json_mode,
            },
            sort_keys=True,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    value: object
    stored_at: float


@dataclass
class CompletionCache:
    """In-process, TTL-bounded, size-bounded.

    In-process on purpose. A shared cache across replicas would need Redis, an
    invalidation story and a serialisation format for `Completion` - and the
    thing being saved is a repeated question inside one run, which does not
    cross a process boundary. `core/memory/` is where a shared one would go if
    that changes.
    """

    ttl_seconds: float = DEFAULT_TTL_SECONDS
    max_entries: int = DEFAULT_MAX_ENTRIES
    clock: Clock = field(default_factory=lambda: _monotonic)
    hits: int = 0
    misses: int = 0
    _entries: OrderedDict[str, _Entry] = field(default_factory=OrderedDict)

    def get(self, key: CacheKey) -> object | None:
        """The cached value, or None.

        None means "ask the model". An expired entry is removed on the way past
        rather than left to be evicted later, so a stale value cannot be
        returned by a future bug in the eviction path.
        """
        digest = key.digest()
        entry = self._entries.get(digest)
        if entry is None:
            self.misses += 1
            return None

        if self.clock() - entry.stored_at >= self.ttl_seconds:
            del self._entries[digest]
            self.misses += 1
            return None

        # Recency is updated on read, so a repeatedly-asked question survives
        # eviction while a once-asked one does not.
        self._entries.move_to_end(digest)
        self.hits += 1
        return entry.value

    def put(self, key: CacheKey, value: object) -> None:
        """Store, evicting the least recently used if that would overflow."""
        digest = key.digest()
        self._entries[digest] = _Entry(value=value, stored_at=self.clock())
        self._entries.move_to_end(digest)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Drop everything, counters included.

        The counters go too: they describe the contents, and a hit rate measured
        against entries that no longer exist describes nothing.
        """
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    @property
    def size(self) -> int:
        return len(self._entries)


def _monotonic() -> float:
    """Monotonic, not wall clock. A clock adjustment must not expire the cache."""
    import time

    return time.monotonic()
