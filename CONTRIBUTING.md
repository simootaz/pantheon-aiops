# Contributing to Pantheon

Read [docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md) first — it is the map of
this repository, and it tells you where things go.

## Git Flow, mandatory

`main` and `develop` exist. **Never commit directly to either.**

```bash
git checkout develop && git pull
git checkout -b feature/<name>
# ... work, with conventional commits ...
git checkout develop && git merge --no-ff feature/<name> && git branch -d feature/<name>
```

- Conventional commits: `feat:` `fix:` `refactor:` `chore:` `docs:` `test:` `build:` `ci:`
- Merge only when the branch's checks **actually pass** — not when they look
  like they would.
- `--no-ff` always, so a feature stays visible as a unit in history.

Commit messages carry no tool attribution of any kind — no co-author trailers,
no generated-by footers, no emoji sign-offs
([ADR 0003](docs/adr/0003-neutral-repository-documentation.md)).

## The repository map is part of every change

> Whenever you **create, move, rename or delete a directory or a significant
> file**, you update `docs/REPOSITORY_MAP.md` **in the same commit**: the folder
> map, the "Where do I put X?" table, and a new row in the structure changelog.

A branch that changes structure without touching the map is incomplete. A stale
map is worse than no map, because people trust it.

## Generated code — never hand-edit

| Directory | Generated from | By |
|---|---|---|
| `core/contracts/export/` | `core/contracts/*.py` | `codegen/export_schemas.py` |
| `pkg/contracts/` | the JSON Schema | `codegen/gen_go.sh` |
| `dashboard/types/generated/` | the JSON Schema | `codegen/gen_ts.sh` |

To change any of them: **edit `core/contracts/`, run `make codegen`, commit the
contract change and the regenerated output together.**

`make codegen-verify` regenerates into a temp directory and diffs. Any drift
fails, in pre-commit and in CI.

> **Hand-writing a mirrored type in Go or TypeScript is forbidden.** If you need
> a shape that does not exist, add it to `core/contracts/`. You never type it
> out twice.

Generator versions are pinned in `gen_*.sh`, and `codegen-check.yml` asserts the
workflow agrees with the scripts. If they diverge, CI regenerates with a
different tool and reports drift that is not a contract change — which is
exactly how a drift detector gets ignored.

## Guards

This repository is mostly guards. Treat them as the primary artifact.

### Every guard is verified against a planted violation, in both directions

> **If you have not seen it red, you have not tested it.**

A guard that has only ever been observed passing is unverified, however correct
it looks. It might be passing because the invariant holds — or because it cannot
detect a violation. Those are indistinguishable from outside, and the second is
worse than no guard, because it buys false confidence.

So when you add or change a guard:

1. break the invariant deliberately,
2. run the guard alone and **watch it fail**,
3. revert, and confirm it goes green.

Record it in [docs/guard-verification.md](docs/guard-verification.md).

This rule has paid for itself three times, each on a guard that looked correct
and was passing continuously:

- `verify.sh` raised an exception instead of reporting drift — the drift
  detector had never worked;
- `satisfies readonly A2UIComponentType[]` caught component *removals* only, so
  a component added server-side would have gone silently unrendered while the
  comment claimed full coverage;
- three guards asserted a substring that also appeared in the *comment*
  describing it, so deleting the real mechanism left them green.

### The rule has a guard of its own

Fifteen branches into a project with *"if you have not seen it red, you have not
tested it"* as its central rule, an assertion ending in `or True` still got
written. Vigilance did not catch it. So it is now enforced:

- ruff's `SIM221`/`SIM222` catch `x or not x` and `... or True` at lint time;
- `tests/unit/test_no_tautological_assertions.py` catches what ruff does not —
  `assert True`, `assert 1`, `assert "literal"`, comparisons of two constants,
  empty test bodies, and test functions with no assertion mechanism at all.

Both directions are pinned: the detector has tests proving it fires on each
pattern *and* does not fire on real assertions.

The original escaped because the iteration loop ran
`ruff check --fix -q … >/dev/null 2>&1`. **A linter whose output you discard is
not a linter** — which is the same mistake as a guard that only ever passes.

### A check whose output is suppressed is not a check

A distinct failure from a guard that cannot fail, and the more instructive one:
**the rule existed, was selected, and fired — and the result was thrown away.**

`assert … or True` reached a commit because the iteration loop ran
`ruff check --fix -q … >/dev/null 2>&1`. Ruff's `SIM222` flagged it correctly.
Nobody saw.

So:

- Never discard a checker's **verdict**. `|| true`, `; true` and a bare `exit 0`
  after a check turn a failure into a pass.
- Discarding **chatter** is fine when the exit code still decides. `verify.sh`
  sends generator stdout to `/dev/null` under `set -e` and prints every captured
  diff to stderr on failure — the noise goes, the verdict stays.
- `continue-on-error` must always be paired with a later step reading
  `steps.<id>.outcome`. `security.yml` uses it correctly, so SARIF uploads before
  the job fails; without the later step it would mean "ignore this result".
- If you capture output to a file, **print it on failure**. Drift detected and
  not reported is drift nobody fixes.

Guarded by `tests/unit/test_checks_are_not_suppressed.py`, which checks Makefile
check targets, every workflow's `continue-on-error` usage, and that `verify.sh`
prints as many diffs as it captures.

### Fixing the code beats narrowing the guard

When a guard fires, the default is to fix what it found.

Narrowing a guard to make it pass converts a real finding into a permanent blind
spot, and it is almost always the cheaper-looking option in the moment. If a
guard is genuinely wrong, fix the *guard*, re-verify it in both directions, and
say why in the commit — do not quietly shrink its scope.

Two worked examples in this repository: `Capability` was renamed to
`credential_ref` rather than exempted from the secret-shaped-field scan, and the
`Image` component was re-admitted **reference-based** rather than having the URL
check relaxed.

### Don't let documentation satisfy a mechanism check

Assert against the mechanism, not the file. `"fail" in template` is true because
a comment says "fail closed". Strip comments first — `_mechanism_only()` in
`tests/unit/test_repo_structure.py` exists for this.

## Local checks

```bash
make lint typecheck test      # Python: ruff, mypy --strict, pytest
make lint-go test-go          # Go: gofmt, vet, golangci-lint, build, test
make lint-ts test-ts          # TypeScript: biome, tsc, vitest
make codegen-verify           # contract drift
```

Deploy changes additionally need:

```bash
helm lint deploy/helm/pantheon                          # ×3 value sets
terraform -chdir=deploy/terraform fmt -check -recursive
docker compose -f deploy/compose/docker-compose.yml config -q
```

Workflow changes need `actionlint` and `zizmor`.

**Go note:** `go build ./...` does not work from the repo root — the root is not
a module, and adding a `go.mod` would not help because nested modules are pruned
from a parent's walk, so it would report success while building nothing. Use
`make lint-go`, `make test-go`, and
`go build github.com/simootaz/pantheon-aiops/...`.

## Where things go

The full table is in the
[repository map](docs/REPOSITORY_MAP.md#where-do-i-put-x). The rules people trip
over:

| | |
|---|---|
| A model name inside an agent | ❌ Declare `ModelRequirements`; Delphi resolves |
| A secret anywhere near an agent | ❌ Request a capability; the connector redeems the lease |
| A URL an agent supplies | ❌ An `ArtifactRef`; the server resolves it |
| Raw HTML in agent-generated UI | ❌ The `A2UIComponentType` allowlist only |
| A Go or TS type mirroring a Python model | ❌ `core/contracts/`, then `make codegen` |

## Adding an ADR

Record decisions with consequences in `docs/adr/NNNN-title.md`, and index it in
[docs/adr/README.md](docs/adr/README.md).

State what you **rejected** and why. The next person will propose it again, and
the ADR is the answer — that is most of what makes an ADR worth writing.

## Licence

Apache 2.0. Contributions are accepted under the same licence.
