"""Capability probes - models describe themselves by being asked to perform.

There is deliberately no hardcoded model table. One would be stale within weeks,
would exclude every model released after this file was written, and would
describe the marketing rather than the deployment - a model behind one gateway
does not always behave like the same model behind another.

WHAT IS PROBED, AND WHAT IS NOT
---------------------------------
The module docstring used to promise four probes. Two of them cannot be written
against the adapter that exists:

| capability   | probe                                   | status |
|--------------|-----------------------------------------|--------|
| (reachable)  | a trivial completion                    | probed |
| `JSON_MODE`  | ask for JSON, check it parses           | probed |
| `STREAMING`  | -                                       | assumed baseline |
| `TOOL_USE`   | would need `complete(tools=...)`        | **NOT probed** |
| `VISION`     | would need an image part in the request | **NOT probed** |

`Provider.complete` takes a prompt, a system message, a token ceiling and a JSON
flag. There is nowhere to put a tool schema or an image, so a TOOL_USE probe
would be measuring a request that never carried tools - and would report
whatever the model said about tools in prose as though it were a capability.

Those two are recorded as **unprobed**, which is a different answer from absent.
`CapabilityMatrix` keeps `present` and `absent` apart precisely so this
distinction survives, and the resolver can say "not known to support tool use"
rather than "does not support tool use".

WHY UNPROBED IS A HARD STOP ANYWAY
------------------------------------
It is, and that is correct. Hermes declares `JSON_MODE`, nothing had ever
probed, and every Hermes run failed with `Unresolvable` - which looked like a
broken resolver and was really a system with no observations in it. The fix is
to probe, not to assume: a model assumed to have JSON_MODE and lacking it
returns prose where the caller parses JSON, and the caller reports a parse error
about a model that was never asked properly.

PROBING COSTS MONEY
---------------------
Every probe is a real request. `probe_model` is called on demand - a settings
"Test connection", a configuration change, or a stale entry - never on a timer
and never during an investigation.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from core.contracts.llm import Capability
from core.llm.capability_matrix import CapabilityMatrix, Probed
from core.llm.provider import BASELINE_CAPABILITIES, Provider, ProviderError

#: Capabilities this module can actually establish. Anything outside it is
#: recorded as unprobed, and `tests/unit/test_capability_probes.py` fails the
#: build if an implemented agent requires something not in here - a requirement
#: nothing can ever satisfy is worse than an unimplemented probe, because it
#: presents as a resolver bug.
PROBEABLE: frozenset[Capability] = frozenset({Capability.JSON_MODE})

#: The smallest request that still proves the round trip works. Deliberately
#: tiny: this is charged to whoever clicked "Test connection".
_REACHABILITY_PROMPT = "Reply with the single word: ok"

#: Asking for JSON without a schema. A schema would test the model's
#: schema-following, which is a different and harder claim than "can return
#: parseable JSON when asked" - and JSON_MODE is the second one.
_JSON_PROMPT = 'Reply with this exact JSON object and nothing else: {"ok": true}'

#: Enough for a word or a small object. A ceiling too low makes a reasoning
#: model spend its whole budget thinking and return empty - which this project
#: has already been bitten by, and which would read as a model that cannot do
#: JSON rather than one that was not given room to answer.
_PROBE_TOKENS = 256


async def probe_model(provider: Provider, model_id: str) -> Probed:
    """Ask one model what it can do, by asking it to do it.

    Never raises. A provider that is down is an observation - recorded with its
    error so a caller can tell "we tried and it refused" from "nobody has
    looked", and so a retry can be scheduled for the first and not the second.
    """
    at = datetime.now(tz=UTC)
    started = time.perf_counter()

    try:
        first = await provider.complete(
            model_id=model_id, prompt=_REACHABILITY_PROMPT, max_tokens=_PROBE_TOKENS
        )
    except ProviderError as unreachable:
        return Probed(
            provider_id=provider.provider_id,
            model_id=model_id,
            at=at,
            error=f"unreachable: {unreachable}",
        )

    latency_ms = int((time.perf_counter() - started) * 1000)

    present = set(BASELINE_CAPABILITIES)
    absent: set[Capability] = set()

    if not first.text.strip():
        # Reachable, but it answered nothing. Not a capability failure - the
        # round trip worked - so it is recorded as an error rather than as an
        # absent capability, because "returns empty" is a fact about this
        # request and not about what the model can do.
        return Probed(
            provider_id=provider.provider_id,
            model_id=model_id,
            at=at,
            present=frozenset(present),
            median_latency_ms=latency_ms,
            error="answered with empty text; raise the token ceiling and probe again",
        )

    if await _speaks_json(provider, model_id):
        present.add(Capability.JSON_MODE)
    else:
        absent.add(Capability.JSON_MODE)

    return Probed(
        provider_id=provider.provider_id,
        model_id=model_id,
        at=at,
        present=frozenset(present),
        absent=frozenset(absent),
        median_latency_ms=latency_ms,
        # NOT read from a vendor table. Nothing here measures a context window -
        # doing so means growing a prompt until the provider refuses, which is
        # expensive and rude - so it stays 0 and `min_context` requirements go
        # unsatisfied rather than satisfied on a guess.
        context_window=0,
    )


async def _speaks_json(provider: Provider, model_id: str) -> bool:
    """Whether asking for JSON produces JSON.

    Parsed rather than pattern-matched. A model that emits ```json fences around
    valid JSON has not returned JSON, and a caller doing `json.loads` on it gets
    an exception - so this measures what the caller will actually do.
    """
    try:
        answer = await provider.complete(
            model_id=model_id,
            prompt=_JSON_PROMPT,
            max_tokens=_PROBE_TOKENS,
            json_mode=True,
        )
    except ProviderError:
        # A provider that refuses `json_mode` outright is a model without it.
        # Distinct from unreachable, which was already handled above.
        return False

    try:
        json.loads(answer.text)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


async def probe_into(
    matrix: CapabilityMatrix, provider: Provider, model_ids: list[str]
) -> list[Probed]:
    """Probe several models and record every result, including the failures.

    Sequential rather than concurrent: these are real requests against one
    provider, and firing them in parallel is how a "Test connection" button
    trips a rate limit and reports every model as unreachable.
    """
    results: list[Probed] = []
    for model_id in model_ids:
        probed = await probe_model(provider, model_id)
        matrix.record(probed)
        results.append(probed)
    return results
