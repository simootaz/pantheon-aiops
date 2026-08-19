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

### The pre-merge ritual

**Never chain a branch switch or a merge behind anything.** Verify, then act, as
separate commands:

```bash
git commit -F - <<'MSG'
...
MSG
git log --oneline -1        # is the NEW commit at HEAD?
git status --porcelain      # empty?
# only now:
git checkout develop && git merge --no-ff feature/<name>
```

This is a rule rather than a resolution because the failure has happened. A
commit was blocked by the gitleaks hook, but the command was written as
`git commit … ; git log … && git checkout develop && git merge … && git branch -d …`.
`git log` succeeded, so the chain continued: it merged nothing, reported
"Already up to date", and deleted the branch.

Nothing was lost that time — the branch had no commits of its own, so `-d`
removed a pointer — but the work sat staged on `develop`, which the first rule
on this page forbids. `&&` only guards against the *immediately preceding*
command, and a merge is not something to run on that assumption.

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
a comment says "fail closed".

This was fixed five separate times before the fix was made the **default**.
`tests/mechanism.py` now owns it, and reading a file any other way fails the
build (`tests/unit/test_mechanism_helper_is_used.py`). Four entry points, so the
intent is explicit at every call site:

| Function | For |
|---|---|
| `read_mechanism(path)` | scanned for a mechanism — comments stripped |
| `read_data(path)` | handed to a parser (JSON, YAML, TOML, `ast`) |
| `read_verbatim(path, why=…)` | the comments *are* the assertion; reason required |
| `read_scannable(path)` | repo-wide sweeps over possibly-binary files |

`read_mechanism` **refuses Markdown**: a leading `#` is a heading there, and
stripping it would turn `"## Folder map" in body` into a guard that asserts
nothing. That refusal exists because this migration nearly introduced it.

### Aim a guard at the level where the defect can exist

Before writing a guard, ask where the mistake would actually be made. A helper
that takes an absolute deadline cannot demonstrate a caller passing a duration;
a function that normalises a path cannot show a caller passing a relative one.
Guard the seam, not the well-behaved component beside it.

A guard aimed at the wrong layer passes for exactly the same reason a correct one
does, so only a planted violation distinguishes them. Worked example, and the
one that cost the most to notice, in `docs/guard-verification.md`.

### A component that cannot honour a parameter must say so

Related to the suppressed-check rule, and found the same way — by measuring
instead of trusting. The simulator accepted `--speed 2880`, delivered 259x, and
reported success. Nothing was broken: the data was correct in simulated time.
But every wall-clock claim made about that run was wrong, and nothing said so.

If a component takes a parameter it cannot always meet, it reports what it
actually achieved. `RunReport.achieved_speed` and `kept_up` exist for this, the
runner prints the shortfall, and the gate asserts on the delivered speed rather
than the requested one. Degrading quietly is the failure; degrading is fine.

### A bound applied per-item destroys the shape it bounds

Log volume had to be capped or a compressed run would spend itself talking to
Loki. The obvious cap — at most N lines per pod per tick — is wrong in a way
that passes every test: past any useful compression *every* pod saturates N, so
the busiest service at 14:00 emits exactly as much as the quietest at 04:00. The
cap silently converted the log stream into the flat line the metrics were
carefully built to avoid.

A single ratio applied uniformly bounds the same total and preserves every
relative volume. When you must throttle something, throttle it proportionally,
derive the ratio from a fixed reference rather than the current value, and
report the ratio — see `LogGenerator.sampling_ratio`.

## Toolchain setup

**Go 1.25.13.** `go.work`, all five `go.mod`, `Dockerfile.connector-go` and the
workflows declare 1.25, and the pinned generators require it: `go-jsonschema`
v0.24.1 and `golangci-lint` v2.12.2 both need >= 1.25.0.

Set `GOTOOLCHAIN=local`:

```bash
go env -w GOTOOLCHAIN=local
```

This is load-bearing, not tidiness. With the default `auto`, a machine running
an older Go silently downloads whatever a tool asks for and prints one line
saying so. That line appeared on every local `make codegen` run for days while
CI - which sets `GOTOOLCHAIN=local` - failed fifteen times on the mismatch.
`local` turns it into an error you cannot read past.

A working setup on this machine, for reference: the official archive extracted
to `~/go-toolchains/go`, with `~/go-toolchains/go/bin` on the user PATH. Any
install location works; what matters is that `go version` reports 1.25.x and
`go env GOTOOLCHAIN` reports `local`.

**Other tools.** `uv` owns Python. `pnpm` comes from `packageManager` in
`dashboard/package.json`. `trivy` is worth installing at the version CI pins -
0.70.0 - because its findings do not appear in the CI console log, only in the
uploaded SARIF, so reproducing locally beats pushing to see.

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

## Configuration

`core/config.py` is the **only** module that reads the environment. Everything
else imports from it:

```python
from core.config import get_settings

settings = get_settings()
httpx.get(f"{settings.prometheus.base}/api/v1/query")
```

Adding a setting means three things, and a guard checks each:

1. a typed field on the right group in `core/config.py`;
2. an entry in `.env.example` — the template and the model must agree in **both**
   directions, so a field with no entry and an entry with no field both fail;
3. if it is a secret, no default, and a row in `REQUIRED_IN_PRODUCTION` so
   `PANTHEON_ENV=production` refuses to start without it.

Never reintroduce `os.environ.get("SOMETHING", "a-default-that-looks-fine")`.
That pattern has two failure modes and both are silent: dev and prod drift apart
one call site at a time, and a typo'd name falls back to a working-looking
default forever. `tests/unit/test_centralized_config.py` fails the build on it.

Go modules read their own environment, but the **names** must match
`.env.example` — a connector on `PROM_URL` while Python is on `PROMETHEUS_URL`
configures two different systems that look like one.

## Cutting a release

The version is declared in **exactly one place**: `version` in `pyproject.toml`.
Everything Python reads it back from installed package metadata at runtime, so
`api.__version__` and `/health` cannot drift from it.

Three manifests cannot read Python metadata and therefore restate it. They are
held equal by `tests/unit/test_version.py` rather than by memory:

| File | Field |
|---|---|
| `deploy/helm/pantheon/Chart.yaml` | `version` and `appVersion` |
| `dashboard/package.json` | `version` |

To release:

1. Bump `version` in `pyproject.toml`.
2. Run `uv sync` so the installed metadata matches, then `make test` — the
   guards fail if any manifest still disagrees.
3. Update the four fields above to the same number.
4. Merge to `develop`, then to `main`.
5. Tag the merge commit `vX.Y.Z`, matching the declared version exactly.

Step 5 is checked: if a `v*` tag points at a commit whose tree declares a
different version, `make test` fails. CI fetches tags so that check is real
there and not vacuous.

This exists because `/health` served `0.1.0` for the whole of a v0.2.0 release.
The number was written down five times and only the tag moved.

## Licence

Apache 2.0. Contributions are accepted under the same licence.
