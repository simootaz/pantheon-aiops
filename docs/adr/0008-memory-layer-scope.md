# ADR 0008 — What `core/memory/` is, and what it is not yet

- **Status:** Accepted
- **Date:** 2026-08-28
- **Decided on branch:** `feature/lethe-detection`
- **Implementation:** `cache.py` now. `vector_store.py` deferred to Phase 5. `repository.py` deleted.

## Context

`core/memory/` was scaffolded in Phase 0 as three modules — `vector_store`,
`repository`, `cache` — and Phase 2 lists "memory" among its deliverables.
Reaching that item, each of the three turned out to be a different kind of
problem, and only one of them is a Phase 2 problem.

Nothing had been committed anywhere: no ADR, no dependency in `pyproject.toml`,
no service in any Compose file. The scaffold was three docstrings.

## `repository.py` — deleted, because it already exists

Its docstring reads *"relational persistence for Investigations, Findings,
Verdicts and Actions."*

`core/store/investigations.py` is exactly that. It has a Protocol, an in-memory
implementation, a Postgres implementation split out at the coverage-floor
boundary, and a live gate (`make test-flow-one`) that reads an Investigation back
on a second connection. Zeus writes through it at every state change.

Two modules for one job do not stay in step. One grows a field the other lacks,
a caller picks the wrong one, and the bug is a record that saved and vanished.

The stub is removed rather than left in place, because a stub reads as planned
work. Someone would eventually have built it, correctly according to its
docstring, and the duplication would have arrived with a passing test suite.

> Where Investigation persistence lives: `core/store/`. There is no second
> answer, and this ADR exists so nobody has to rediscover that.

## `vector_store.py` — deferred to Phase 5, with the trigger named

Its only consumer is **Mnemosyne** (`agents/knowledge/`), which is Phase 5 and
whose manifest currently declares no memory tool at all. Nothing reads it.

The choice of backend is genuinely open — pgvector on the Postgres that is
already deployed, or a separate service such as Qdrant — and each has a real
case. What is not open is whether to decide now:

**Building a store with no reader means guessing the query shape.** Recall for
"find past investigations resembling this one" could be over a Finding's
template, over a Verdict's root cause, over the full Investigation document, or
over an embedding of the trigger. Those are four different schemas and two
different indexing strategies, and the one that is right is the one Mnemosyne
asks for. Committed early, the guess becomes a migration.

The operational weight is not free either. A separate service is a Compose
entry, a Helm chart, a network policy, a backup path and a restore drill.
pgvector is lighter but still an extension pinned into the Postgres image and a
second reason that image cannot be swapped.

### What forces the decision

Any one of these, and it is revisited rather than inherited:

1. **Mnemosyne is scheduled.** Its manifest declares a memory tool, which fixes
   the query shape.
2. **A second consumer appears.** If anything other than Mnemosyne wants
   similarity search, the shape is no longer one agent's private concern.
3. **Investigation volume makes `recent(limit)` insufficient** for the API's own
   listing — at which point a query layer is needed regardless of embeddings,
   and the two decisions should be made together.

Until then `vector_store.py` keeps its stub, and this section is why.

## `cache.py` — built, and only for model completions

The one piece with a caller today. It caches **LLM completions and nothing
else.**

### Why not connector responses

A cached Prometheus read answers with the past. During an incident that is
exactly when the difference matters, and the failure is silent — an agent
reasons correctly over a number that was true five minutes ago and reaches a
conclusion nobody can reproduce.

The saving would be small anyway. A connector call is one HTTP round trip on the
local network; a model call is money and seconds.

### Why a completion is safe to cache when a metric read is not

The cache key is the **whole request** — model, prompt, system, token ceiling and
JSON mode. Agents that consult Delphi embed the data they are reasoning about in
the prompt: Hermes puts the query result in it, and Lethe would put the template
set in it. So if the underlying data changed, the prompt changed, and the key
changed. A hit means the identical question was asked of the identical model
about the identical data.

That is a property of how the callers build prompts, not a guarantee of the
cache. It is stated here and asserted in `tests/unit/test_completion_cache.py`,
because a future caller that put a bare question in the prompt and the data
somewhere else would break it silently.

### A hit must not be recorded as a paid call

`ResolutionRecord` feeds "what did this investigation cost". A cache hit costs
nothing, and replaying the original record would double-count spend — the total
would climb while no money moved.

A hit is therefore recorded as a hit, with zero cost and zero tokens, and the
record says which. An investigation that spent nothing on its second identical
question should be visibly cheaper, not invisibly the same.

## Consequences

- `core/store/` is the single answer for Investigation persistence.
- `core/memory/vector_store.py` stays a stub with a named trigger, so deferral is
  a decision with conditions rather than an omission.
- Delphi gains an optional cache. It is off unless a cache is supplied, so the
  gateway's behaviour is unchanged for every caller that does not opt in.
- Phase 2's "memory" deliverable is met by `cache.py` plus this ADR, and the
  Phase 2 row in `docs/REPOSITORY_MAP.md` is corrected to say so rather than
  implying three modules landed.
