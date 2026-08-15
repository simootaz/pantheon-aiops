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
every file reported by `git ls-files` and fails if a forbidden substring appears
in any path or any file's contents. It also asserts that the repository map is
tracked and still contains all nine sections — so a "neutralisation" that
quietly deleted the map instead of moving it would fail rather than pass.

The scanner necessarily spells the forbidden terms out, so it excludes itself
and nothing else. Untracked and gitignored files are deliberately out of scope:
they never enter the repository.

Commit messages are **not** covered by the test — git history is not a file
tree. They are covered by the tool configuration described in the addendum.

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

## Addendum — history rewrite

_To be completed once the rewritten history is pushed._

<!-- TODO: record the rewrite date, the before/after commit count, confirmation
     that tree hashes were unchanged, and the local setting that prevents
     recurrence. -->
