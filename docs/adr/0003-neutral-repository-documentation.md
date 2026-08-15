# ADR 0003 — Neutral repository documentation

- **Status:** Accepted
- **Date:** 2026-08-15
- **Decided on branch:** `feature/repo-map-neutralization`

## Context

This repository is going public.

Which local tools a contributor uses — editor, shell, assistant, linter plugin —
is their own business. It is not part of the project, it is not something a
reader needs, and it does not belong in tracked files. A public repository
should describe *the software*, not the workstation it was written on.

Two specific fingerprints had accumulated:

1. **A tool-specific filename.** The canonical repository map lived at the root
   under a filename derived from one particular assistant tool. That name was
   incidental — the file's job is to be the map, and its name should say so.
2. **Co-author trailers in commit messages.** Commits carried an automatically
   appended trailer attributing a tool as co-author, which surfaces as a
   co-author badge on the hosting platform.

## Decision

**No tracked file — path or contents — references an assistant tool. No commit
message does either.**

### The repository map

`docs/REPOSITORY_MAP.md` is the canonical map. It carries all nine sections it
always had: project identity, language boundaries, folder map, "Where do I put
X?", generated files, standing decisions, Git Flow rules, commands, phase
roadmap and the structure changelog.

The standing instruction is unchanged in substance, only in target: **any
structural change updates `docs/REPOSITORY_MAP.md` in the same commit.**

### Local pointer files are permitted, but never tracked

A contributor may keep a root-level file pointing at the map for their own
tooling. Such files must be excluded from git and contain nothing but the
pointer. The rule is about what enters the repository, not about what sits in a
working directory.

**They are excluded per-clone via `.git/info/exclude`, not via `.gitignore`.**
This is not a stylistic preference. `.gitignore` is a *tracked* file, and to
ignore a name you have to write that name down — so listing them there would
reintroduce exactly the fingerprint this ADR removes. The repository's own
neutrality guard caught this, which is the argument for having it.

`git rm --cached` was used to drop the previously tracked pointer without
deleting anyone's local copy.

On a fresh clone, append your tool's pointer filename and its config directory
to `.git/info/exclude` — one line each. That file is per-clone and never
tracked, so the names stay on your machine.

Note that this document does not spell those names out either: the neutrality
guard scans ADRs like every other tracked file, and an ADR that violated its own
rule would be a poor advertisement for it.

**Trade-off, stated plainly:** per-clone excludes are not shared, so each
contributor adds their own once. That is the cost of the rule, and it is smaller
than the thing it buys.

### Commit messages

No tool attribution of any kind: no co-author trailers, no generated-by footers,
no emoji sign-offs. This applies to every future commit.

Recurrence is prevented at source by local tool configuration rather than by
discipline — see the addendum below.

### Provider configuration is not a fingerprint

`core/llm/` exists to call a language model, so the environment surface must
name model configuration. That is the *product's* dependency, not a record of
how the repository was authored.

It is expressed provider-neutrally — `PANTHEON_LLM_PROVIDER`,
`PANTHEON_LLM_BASE_URL`, `PANTHEON_LLM_API_KEY`, `PANTHEON_LLM_MODEL` — for the
same reason object storage is
([ADR 0001](0001-object-storage-minio.md)): the platform must not be welded to
one vendor. Point the base URL at any compatible endpoint, including a
self-hosted one.

## Enforcement

This is checked, not remembered. `tests/unit/test_repo_neutrality.py` walks
every file reported by `git ls-files` and fails if an **authorship-attribution
pattern** appears in any path or any file's contents. It also asserts that the
repository map is tracked and still contains all nine sections — so a
"neutralisation" that quietly deleted the map instead of moving it would fail
rather than pass.

The scanner necessarily spells the patterns out, so it excludes itself and
nothing else. Untracked and gitignored files are deliberately out of scope: they
never enter the repository.

Commit messages are **not** covered by the test — git history is not a file
tree. They are covered by the tool configuration described in the addendum.

---

## Amendment — the ban targets attribution, not the vendor namespace

_2026-08-15, on branch `feature/neutrality-guard-narrowing`._

The guard was first implemented as a **substring ban** on a handful of words,
including a vendor name. That was the wrong shape, and it surfaced the moment
[ADR 0004](0004-llm-provider-abstraction.md) needed to document which providers
Pantheon supports.

**The problem.** One vendor name was doing double duty: it identified both an
assistant tool *and* a legitimate API dialect the product must support. A
substring ban therefore blocked real product content — a supported-providers
table, example model identifiers in tier defaults, dialect documentation,
endpoint hosts — while catching nothing a pattern ban would miss.

**The distinction.** What must not appear is a claim that this repository was
*authored by* a tool. That is a phrase, not a word:

| Banned — attribution | Allowed — product content |
|---|---|
| A co-author trailer naming an assistant | A supported-providers table naming vendors |
| "Generated with …", "Created by …", emoji sign-offs | Example model identifiers in tier defaults |
| An assistant's local pointer filename | API endpoint hosts and dialect names |
| An assistant's config directory | Provider adapter modules and their docs |

Nobody infers AI authorship from a provider list — every tool in this space
ships one. Pantheon is an LLM platform, so naming providers is describing the
software, which is exactly what a public repository is *for*. This is the same
line ADR 0001 already sits on: it names MinIO, AWS S3, Ceph, Wasabi and R2
freely, because those are the product's supported backends.

**The rule, restated.** The guard matches attribution patterns:

- a co-author trailer naming an assistant,
- authorship or generation attributed to an assistant,
- an emoji sign-off,
- an assistant's pointer filename or config directory.

Vendor names, model identifiers, API hosts and provider documentation are
explicitly permitted, anywhere.

**Pinned against regression.** `test_guard_permits_provider_documentation` feeds
the scanner a realistic provider table — several vendors, model ids and endpoint
URLs — and asserts it produces no findings.
`test_guard_catches_authorship_attribution` asserts the patterns that matter are
still caught. Between them, the guard's own behaviour is now tested in both
directions, so it cannot be quietly re-broadened into a vendor ban or quietly
hollowed out.

## Consequences

**Good**

- The public repository describes the software and nothing else.
- The map has a name that says what it is, which is better documentation
  regardless of the original motivation.
- Provider-neutral model configuration is a genuine architectural improvement
  that fell out of the same rule.

**Costs**

- One more guard to keep passing, and a forbidden-substring list to maintain.
- Contributors relying on the old root filename need it gitignored locally.
- Historical commit messages required a rewrite; see the addendum.

## Alternatives considered

| Option | Why not |
|---|---|
| Delete the map, fold it into `README.md` | The README is for newcomers; the map is a working reference. Merging them serves neither. |
| Keep the tool-specific filename, scrub only commit messages | The filename is the most visible fingerprint of the three. |
| Rely on review discipline | Conventions nothing checks are conventions that rot — the same reasoning behind the structural guards. |

---

## Addendum — history rewrite, 2026-08-15

The decision above governs new work. Existing history also carried the
fingerprints, so it was rewritten once, on 2026-08-15, and force-pushed.

### What was found

An audit separated two layers, which matters because only one of them existed:

| Layer | Affected |
|---|---|
| Author / committer identity | **0 commits.** No identity was ever attributed to a tool. |
| Commit message trailers | **36 of 45 commits**, one appended co-author line each. |
| The old map filename in messages | **10 lines across 4 commits**, including 3 subject lines. |
| Generated-by footers, emoji sign-offs | 0 |

The co-author badge visible on the hosting platform came entirely from the
message trailers, not from commit authorship.

### What was done

A single `git filter-repo` pass over all refs:

1. removed every co-author trailer line naming a tool or its domain;
2. replaced the old map filename with `docs/REPOSITORY_MAP.md` throughout,
   a literal substitution that left every message otherwise byte-identical — no
   reflowing, retitling or rewording.

The substitution was dry-run first, dumping the before/after of all 46 affected
lines for review and flagging any that would become self-referential,
tautological or ungrammatical. None did: the rename commits describe the move in
terms of the *new* name, so no "renamed X to X" could form. All refs were
bundled to a backup before the pass.

### Verification

| Check | Result |
|---|---|
| `develop` tree hash | `1aae1120…` → `1aae1120…` — **unchanged** |
| `main` tree hash | `8f57a999…` → `8f57a999…` — **unchanged** |
| Commit count | 45 → 45 |
| Message greps (co-author, tool name, vendor domain, generated-by, emoji) | 0 hits each |
| Distinct identities | contributor + one platform-web commit |
| Full gate | lint, typecheck, test, lint-go, test-go, codegen-verify — all pass |

Identical tree hashes are the load-bearing check: **only metadata changed, no
file content moved.** Commit hashes necessarily changed, so anyone holding an
older clone must re-clone or hard-reset rather than merge.

### Preventing recurrence

The trailer was appended automatically by local tooling, so the fix belongs in
local configuration rather than in reviewer discipline. The relevant tool option
is disabled in a gitignored per-repository settings file, and the committer
identity is pinned locally as well as globally.

### Note on `.gitignore`

Local pointer files are excluded via `.git/info/exclude`, **not** `.gitignore`,
for the reason given above: `.gitignore` is tracked, so naming a file there in
order to ignore it reintroduces the fingerprint. The neutrality guard caught
exactly this during implementation, along with a case where a path had been
re-added to the index by an explicit `git add` — and once a path is tracked,
exclude rules no longer apply to it.
