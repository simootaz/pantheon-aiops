# Guard verification

A guard that has only ever been observed **passing** is unverified, however
correct it looks. It might be passing because the invariant holds, or because it
cannot detect a violation. Those look identical from the outside, and the second
is worse than having no guard at all — it buys false confidence.

So every structural and type-level guard in this repository is verified in
**both directions**:

- **something that should fail, does** — a violation is planted and the guard
  must go red;
- **something that should pass, does** — reverted, the guard must go green.

This page records that audit. It is a snapshot, not a substitute for redoing it
when a guard is added or changed.

## Result, 2026-08-15

| | Count |
|---|---|
| Guards planted-and-verified in both directions | **47** |
| Real weaknesses found | **3** (one bug class) |
| Guards still unverified | 0 |

## The weakness that was found

Three guards shared a single failure mode:

> **The documentation satisfied a guard meant to check the mechanism.**

Each asserted a substring against a whole file, and each file *described* the
thing it was checking for:

| Guard | Asserted | Why it could not fail |
|---|---|---|
| `test_chart_has_a_validation_template_that_fails_closed` | `"fail" in body` | the header comment says *"Fail closed on production installs"* |
| `test_generated_secret_is_marked_and_protected` | `"helm.sh/resource-policy: keep" in body` | the header comment quotes that annotation while explaining it |
| `test_argocd_application_documents_client_side_rendering` | `"client-side" in body` | the phrase appears twice, so removing the warning left one behind |

Verified concretely: deleting **all three** `fail()` calls from
`validation.yaml`, deleting the real `resource-policy` annotation from
`minio-secret.yaml`, and deleting the entire warning block from
`application.yaml` each left the corresponding guard **green**.

### The fix

A `_mechanism_only()` helper strips Helm `{{/* … */}}` blocks and `#` comment
lines before any mechanism assertion runs, so prose can no longer satisfy a
structural check. Where the thing being checked genuinely *is* documentation —
the ArgoCD warning — the guard now requires the whole explanation
(`client-side`, `productionMode`, `lookup`, `rotat`) rather than one phrase.

All three now fail when the mechanism is removed and the comment left intact.

## The same class, caught earlier

This is the third time the rule has paid for itself:

| Branch | What a planted violation revealed |
|---|---|
| `feature/codegen-pipeline` | `verify.sh` used `Path.relative_to()` on a temp dir, so the drift detector raised instead of reporting drift — it had never been observed failing *correctly* |
| `feature/dashboard-scaffold` | `satisfies readonly A2UIComponentType[]` catches component **removals** only. A component added server-side would have gone silently unrendered, while the comment claimed full coverage |
| `feature/docs-baseline` | the three guards above |

Each was a guard that looked right, passed continuously, and did not work.

## Suppressed-check audit, 2026-08-17

Every committed invocation of a tool was reviewed for a discarded verdict:
output redirection, `-q`/`--quiet`, `|| true`, and `continue-on-error`.

**No committed instance was found.** Each hit is legitimate:

| Location | Construct | Why it is correct |
|---|---|---|
| `Makefile` `clean` | `2>/dev/null \|\| true` | `find` returns non-zero when a directory vanishes mid-traversal. A command, not a check. |
| `codegen/verify.sh` ×3 | `>/dev/null` on generators | Only stdout. `set -euo pipefail` still enforces the exit code, and stderr is untouched. |
| `codegen/verify.sh` ×3 | `diff … >"$TMP/x.diff"` | The exit code *is* the condition, and each diff is printed to stderr on failure. |
| `security.yml` ×4 | `continue-on-error: true` | Deliberate: findings upload before the job fails. Every one is paired with `if: steps.scan.outcome == 'failure'`. |
| `ci-deploy.yml` | `>/dev/null 2>&1` in an `if` | Asserting a render *fails*; the exit code is the assertion. |
| `security.yml` | `ls -1 ./*.sarif \|\| true` | A diagnostic listing inside the not-found branch. |

**The only occurrence of the failure was interactive, not committed** — the
`ruff … >/dev/null 2>&1` in an iteration loop. That is unguardable by the
repository, which is why the check now lives in pytest where its result cannot
be redirected away.

Four new guards, each planted: a `|| true` on a check target, a check target with
all output discarded, a `continue-on-error` with no outcome check, and a captured
diff that is never printed.

## Simulator guards, 2026-08-17

`feature/simulator` added 33 unit guards. Fifteen were planted against, each in
both directions: mutate the source so the invariant is genuinely broken, run that
guard alone, require it red, restore, require it green.

| Planted violation | Guard |
|---|---|
| `RESTARTS` removed from `NOISE` | `test_every_metric_has_a_noise_and_a_seasonal_amplitude` |
| `RESTARTS` removed from `SEASONAL_AMPLITUDE` | same |
| `RESTARTS` removed from the `base` table | `test_every_metric_samples_for_every_pod` |
| baseline returns `base` with no season or noise | `test_a_day_of_baseline_is_not_a_flat_line` |
| `diurnal` returns a constant | `test_the_daily_curve_has_a_real_peak_and_trough` |
| weekend multiplier set to 1.0 | `test_weekends_are_quieter_than_weekdays` |
| per-pod log clipping restored | `test_log_sampling_preserves_the_daily_shape` |
| per-pod log clipping restored | `test_log_sampling_preserves_the_gap_between_services` |
| `pods_for` returns `()` instead of raising | `test_pods_for_rejects_a_target_it_does_not_recognise` |
| a pod moved to a node that does not exist | `test_every_pod_sits_on_a_node_that_exists` |
| a phase targeting `chekout` | `test_every_phase_targets_something_that_exists` |
| a log pattern naming a template that does not exist | `test_every_log_pattern_names_a_template_that_exists` |
| restarts scaled by `factor` instead of `offset` | `test_restarts_are_perturbed_by_offset_never_by_factor` |
| two scenarios sharing one root cause | `test_the_five_scenarios_cover_five_distinct_root_causes` |
| a duration passed where a deadline was needed | `test_the_run_loop_honours_speed_across_many_ticks` |

### Aim a guard at the level where the defect can exist

The pacing guard was written first as a direct test of `_sleep_until`, calling it
with a series of absolute deadlines. Planting the original bug left it **green**.

The reason is worth recording, because the guard looked entirely reasonable. The
bug was never inside `_sleep_until` — it was in the *caller*, which passed a
duration where a deadline was needed. A helper that takes a deadline recomputes
the remaining wait from that absolute point on every call, so it self-corrects
however its internals are written. **The defect was not expressible at the layer
the guard was testing.** No amount of care inside that test could have found it.

Rewritten to drive `run()` with the I/O stubbed and assert `kept_up` over 42
ticks, it catches the planted duration immediately. Same invariant, tested one
level up, where the invariant actually lives.

> **Aim a guard at the level where the defect can exist.**
>
> Before writing one, ask where the mistake would actually be made. A unit that
> sanitises its own inputs cannot demonstrate a caller that supplies the wrong
> ones; a function that normalises a path cannot show a caller passing a
> relative one. Guard the seam, not the well-behaved component next to it.
>
> A guard aimed at the wrong layer passes for exactly the same reason a correct
> one does. Only the planting tells them apart.

This is the second distinct way a guard can be unfailable, and it is worth
separating from the first. A guard can be satisfied by *documentation* — the
`_mechanism_only()` class, where prose describing a mechanism matches a check
meant to prove the mechanism is present. Or it can be aimed at the *wrong layer*,
where the invariant holds trivially because the defect belongs somewhere else.
The first is caught by stripping comments. The second is caught only by asking
where the bug would live, and then planting it there.

Both were hit again while writing the Makefile guards on `fix/makefile-verification`:
`test_test_sim_requires_the_stack_rather_than_skipping` extracted its "recipe" by
splitting the file on `"test-sim:"`, which matches the `## test-sim:` help line
first — so the comment block explaining `PANTHEON_REQUIRE_STACK` satisfied a check
meant to prove the variable was actually set. Planting removal of the mechanism,
comment left intact, exposed it. `recipe_for()` now takes only tab-indented
command lines and drops comments among them.

## Comment-stripping centralised, 2026-08-17

`_mechanism_only()` was promoted out of `test_repo_structure.py` into
`tests/mechanism.py`, and all 63 file reads across fourteen test modules were
classified individually. `tests/unit/test_mechanism_helper_is_used.py` fails the
build on any raw read, so the fix is now the default rather than a convention.

Two hazards surfaced during the migration, both of which would have produced
guards that pass while asserting nothing:

* **Markdown.** `test_repository_map_is_tracked_and_canonical` checks for
  `## Folder map`. Stripping `#` lines deletes every heading, so the guard would
  have gone green against a map with no headings at all. `read_mechanism` now
  refuses `.md` outright.
* **The Makefile.** `make help` parses `## name: text` lines — comments used as
  data. Stripping them would have emptied `test_every_target_has_exactly_one_help_line`.

A first attempt at a bulk regex migration corrupted six files, including the new
guard, and was reverted. The classification is not mechanical; each site has to
be read against the assertion it feeds.

### What the tally says

| Entry point | Sites | Meaning |
|---|---|---|
| `read_data` | 25 | parsed, not scanned — comments never mattered |
| `read_mechanism` | 22 | genuine mechanism scans |
| `read_verbatim` | 14 | comments or prose *are* the assertion |
| `read_scannable` | 2 | repo-wide sweeps over arbitrary files |

The 14 verbatim sites are worth separating, because "a guard asserting against
documentation" is only alarming in one of the three cases:

* **Comments used as syntax or data** (6) — Markdown headings, Makefile `##`
  help lines, `# TODO: Phase N` markers, generated-file banners. The `#` is
  structure, not commentary.
* **Exact-text comparisons** (4) — the LICENSE body, the README licence section,
  the committed schema compared byte-for-byte against the renderer.
* **Genuinely asserting that something stays documented** (4) — the ArgoCD
  client-side-render warning, the Cerberus import-boundary note, the
  `artifact_resolution` cross-investigation rejection, and the `UNRESOLVED`
  marker on the A2UI seam.

Only that last group asserts "the docs say X" as its mechanism, and in each case
the documentation *is* the deliverable — an operator-facing warning that
silently disappears is the failure being guarded against. Four out of 63 is a
defensible number; it would not have been visible without doing the count.

## A scanner told to ignore a file, 2026-08-18

A third variant of the suppressed-check class, and the quietest one so far.

Not a discarded exit code, and not a check that cannot fail — a scanner
**configured not to look**. `.gitleaks.toml` allowlisted `.env.example` by path
because the generic-api-key rule fires on `CERBERUS_MASTER_KEY=`, an empty
placeholder, on the strength of the variable name alone.

Tested in both directions, a real `glpat-` token pasted into that file passed
cleanly. Secret scanning was off for the file most likely to receive a pasted
credential, and the config read as a narrow, reasonable exemption.

`condition = "AND"` — path *and* empty-assignment — is the correct shape and did
not behave that way in gitleaks 8.30: it either exempted the whole file or
exempted nothing. Rather than ship a config that could not be verified, the
responsibility was **transferred** and the config says so:

| Where | What it now covers |
|---|---|
| `.gitleaks.toml` | everything except `.env.example`, unchanged — verified by staging a real GitLab PAT and watching it fail |
| `test_the_template_never_carries_a_real_secret` | every `SecretStr` field must be empty in the template |
| `test_the_template_holds_nothing_shaped_like_a_credential` | ten vendor-issued credential shapes, matched against values under **any** name |

The second guard's first version matched names containing KEY, SECRET or TOKEN
and flagged `LLM_MAX_TOKENS` (a count) and `S3_ACCESS_KEY` (an identifier paired
with the secret, not the secret). It is now driven by the settings model, which
*records* which fields are credentials. A control asserts `S3_ACCESS_KEY` still
passes, because a guard that fires on the right thing for the wrong reason is
one refactor away from firing on nothing.

The third closes the hole the exclusion opened from the other side: a credential
pasted under a name no settings field declares — `GITHUB_TOKEN_OLD`, a leftover
from debugging — is caught by neither gitleaks nor the model-driven guard. All
ten shapes were planted under undeclared names and all ten fire.

> An exemption is a transfer of responsibility, not a removal of it. Write down
> where the responsibility went, and test that it arrived.

## Two kinds of guard, and a scanner rule

### An absence assertion, deleted to add the feature

`test_cross_attempt_dedup_is_not_claimed_to_exist` is a new shape here, and the
opposite of everything else on this page. Every other guard protects the code
from drifting away from its documentation. This one protects the **documentation
from drifting ahead of the code**.

It asserts what is true *today* - two retried attempts produce two Finding
objects sharing one deterministic id, and nothing merges them, because no
persistence layer exists to upsert into. Building that upsert **breaks the
test**, which is the point: the failure is the reminder to retire the ROADMAP
row and rewrite the `base_agent` RETRIES docstring in the same commit as the
feature, rather than leaving a true-sounding claim about a component nobody
built.

> **An absence assertion must be deleted to add the feature.** When a docstring
> describes a property the code does not yet have, assert the absence. The test
> that fails when you finally build it is the one that makes the documentation
> catch up.

The overstatement it replaced was "an upsert-shaped consumer cannot duplicate
it" - true of a consumer that did not exist. A design resting on a component
nobody built reads exactly like a design resting on a component that works.

### A scanner must enumerate every form of what it forbids

Four guards in this repository have been too narrow, and each was found by
running rather than by reading:

| Guard | Form it missed |
|---|---|
| `.PHONY` completeness | a backslash continuation, so it never read the second line and reported six false positives |
| the raw-file-read sweep | `.read_bytes()`, while `.read_text()` and `.open()` were covered |
| the step-event guard | `from core.contracts.events import StepStartedEvent` — it walked `Name` and `Attribute` nodes only |
| the alert look-back scanner | `offset 30s` — it enumerated `[range]` selectors only, so a rule needing 40s of history was measured at 10 and given a speed at which it could never fire |

Each looked complete. Each was verified against one planted violation, and that
violation happened to use the one form the scanner understood.

> **A scanner must enumerate every syntactic form of the thing it forbids, and
> planting one form verifies only that form.** Where something is expressible
> several ways - an import versus a reference, `read_text` versus `read_bytes`,
> a continued line versus a single one - plant each way. One green planting on a
> multi-form rule is evidence about one form and silence about the rest.

## The alert gate, and what running it found, 2026-08-18

Two defects, neither visible from the YAML, both found by running the rules
against real Prometheus rather than by reasoning about them.

### A ramp measured against its own trailing average barely moves

The memory rule compared working set against `avg_over_time(...[45s])`. That
reads as a reasonable leak detector and is not one: the fault is a **ramp**, and
a trailing average follows a ramp up, so the ratio sits near 1.2 however far the
leak goes. Measured against Prometheus, it crossed the 1.5 threshold only
momentarily - on the sawtooth of the OOM phase - and never held long enough to
satisfy `for: 10s`.

The same defect had already been diagnosed and fixed for the latency rule
earlier in the branch. It was not carried across to memory. **Fixing one
instance of a class and leaving another is its own failure mode**, and the only
reason it surfaced is that the gate ran every rule rather than a representative
one.

`offset` compares two points instead of a point against a smear, so a sustained
climb reads as sustained.

### A gate that asserts after the run tests retained state

The pushgateway holds the last values pushed. After a run whose fault is still
active, those faulty numbers persist, Prometheus keeps scraping them, and an
absolute-threshold rule keeps firing indefinitely. Three scenarios were passing
partly on that - not on live data.

A self-relative rule is what exposed it: once the run stops, the retained
constant makes the series equal to its own past, the comparison collapses to 1,
and the alert can never fire however long the test waits. The rule was correct
and the gate was wrong.

Both directions now watch **during** the run. The negative case too, and
deliberately: a clean-baseline check that only looked at the end would miss a
rule firing transiently in the middle, which would make it weaker than the
positive checks it exists to qualify.

> **Ask what the pass depends on.** A gate that reads state after the thing
> under test has stopped may be reading an echo. If retained state can satisfy
> the assertion, the assertion is about the store, not the system.
## A claim repeated is not a claim verified, 2026-08-19

The hardest variant so far, because nothing fires and nothing looks wrong.

`dashboard/package.json` correctly declared `packageManager: pnpm@11.21.0`, and
three files said so: `docs/REPOSITORY_MAP.md`, `README.md`, and a comment beside
the step in `ci-dashboard.yml` reading *"action-setup reads `packageManager`
from dashboard/package.json"*. It does not. It reads the **repository root**
`package.json`, and this repo has none, so every dashboard job failed with *"No
pnpm version is specified"*.

`git log --all -S packageManager -- tests/` returns exactly one commit: the fix.
**There was never a guard.** Three independent-looking statements of the same
claim made it feel established, and repetition is not verification - it is the
same assertion counted three times.

> **A claim repeated in several places is still one claim.** Prose describing a
> mechanism is evidence that someone intended it, not that it exists. Only a
> test that has been watched failing is evidence.

### The audit that followed

Every "guarded / enforced / asserted / fails the build" claim across
`docs/REPOSITORY_MAP.md`, `README.md`, `CONTRIBUTING.md`, the ADRs and the
workflow comments was checked against whether a test exists: 128 claim-bearing
lines, 9 naming a specific test - **all 9 resolve to a real test** - and the
remainder describing a mechanism without naming one.

It found a second instance immediately. CONTRIBUTING states that adding a
setting means three things "and a guard checks each". The third - *if it is a
secret, a row in `REQUIRED_IN_PRODUCTION`* - had **no guard**. Four `SecretStr`
fields had fallen outside the required set with nothing noticing, one of them
added in the same session that wrote the claim.

The reason it went unseen is worth naming on its own: the existing tests iterate
**over** `REQUIRED_IN_PRODUCTION`, so they verify every entry present and say
nothing about entries missing. **A guard over a list is not a guard that the
list is complete.** Fixed by partitioning: every `SecretStr` must be classified
required or optional-with-a-reason, and the partition is enforced.

## A threshold that reads as enforced and is not the one enforced, 2026-08-19

`trivy config` failed with `::error::trivy config found CRITICAL or HIGH
misconfigurations`. It had found **37 misconfigurations: 28 LOW, 9 MEDIUM, and
zero HIGH or CRITICAL.**

The step said `severity: CRITICAL,HIGH` beside `exit-code: "1"` and
`format: sarif`. But **`severity` does not filter SARIF** - that format carries
every severity, because code scanning does its own filtering - so `exit-code: 1`
tripped on the LOW findings while every visible signal named a threshold that
was not being applied. `trivy fs` had the identical defect and passed, because
it happened to have no findings of any severity to trip over. A latent guard
bug, passing.

Two things made it expensive to see:

- SARIF output means **the console prints no findings at all**, so the error
  message was the only evidence in the log - and the error message was wrong.
  Diagnosing it meant pulling the alerts from the code scanning API and reading
  trivy's own severity out of each rule's `tags`.
- GitHub's `security_severity_level` is its own remapping, not trivy's label.
  Checking the raw tag mattered; `low`/`medium` in the API and `LOW`/`MEDIUM`
  in trivy agreed here, but confirming that was the step that made the count
  trustworthy.

> **A threshold is enforced by the mechanism that reads it, not by the line that
> declares it.** `severity:` next to `exit-code:` reads like a policy. Whether
> it is one depends on the output format three lines down.

Fixed by giving each step one job: a **report** (`exit-code: 0`, SARIF, every
severity, uploaded) and a **gate** (`severity: CRITICAL,HIGH`, `exit-code: 1`,
`format: table`, so a failure states its reason in the log). Note the effective
threshold *loosens* - from "any finding" to the declared CRITICAL,HIGH. That is
the point: the declared policy becomes the real one, and the 28 LOW and 9 MEDIUM
stay visible as code scanning alerts rather than being suppressed.

Guarded by `test_a_sarif_producing_scan_is_never_also_the_gate` and
`test_every_trivy_report_has_a_gate_of_its_own` - the second because a report
with `exit-code: 0` blocks nothing, and splitting the steps introduces exactly
that way to end up with findings in the UI and a green build.

This is the third setting in this repository that looked applied and did
nothing, after the pnpm overrides in the file pnpm stopped reading and the
`# trivy:ignore:` comment in a Helm template that rendering strips. The shape
recurs often enough to check for directly: **when a setting has no observable
effect, confirm the tool reads it there, in that form, in that mode.**

## A scanner that aborts reports fewer findings, 2026-08-19

`connectors/kubernetes/Dockerfile` held four comment lines and no instructions.
Trivy reported *"dockerfile parse error: file with no instructions"* and exited
1 - which is indistinguishable, from the outside, from exiting 1 because it
found something. Deleting the file let the scan run to completion, and it
immediately reported **five HIGH misconfigurations the abort had been hiding**:
MinIO and the backup CronJob running with writable root filesystems and no
dropped capabilities, while every other workload already used the hardened
context sitting in `values.yaml`.

> **A scanner's exit reason matters as much as its exit code.** Zero findings
> and zero scanning look identical in a green tick and nearly identical in a red
> one. Check that the tool read what it was pointed at.

Guarded at the cause rather than the symptom: every Dockerfile must contain an
instruction, every deploy manifest must parse, and every `.trivyignore` entry
must carry a comment - a bare rule id is the threshold lowered one line at a
time.

A related trap in the same fix: an inline `# trivy:ignore:KSV-0109` in a Helm
template does nothing, because trivy scans the **rendered** chart and rendering
strips template comments. Same shape as pnpm overrides sitting in the file pnpm
stopped reading - a suppression that looks applied and changes nothing.

## The claim that named its own guard, which did not exist, 2026-08-19

The README said the repository map **"cannot go stale without a test failing"**,
and ARCHITECTURE said *"a directory that exists and is not described ... fails a
test"*. Two files, stated as mechanism, in the present tense.

The only test touching the map asserted that it **exists**, is **tracked**, and
carries certain **headings**. Nothing about whether it is current.

The proof was already in the branch that found it. `.trivyignore`,
`dashboard/pnpm-workspace.yaml` and `tests/unit/test_ci_is_runnable.py` were
added and committed without appearing in the map, and the suite stayed green
across three commits. `LICENSE` had been missing from the map for far longer.
Every one was caught by reading, late - the exact mechanism the rule exists to
replace.

> **A claim in the present tense about a test is checkable in seconds, and
> nobody checks it.** "Fails a test" is the easiest sentence in a repository to
> verify and among the least likely to be verified, because it reads like a
> statement of fact rather than a claim.

Now guarded in both directions: every tracked top-level entry must appear in
the map, and every entry the folder-map tree draws must exist. Planted three
ways - a staged file the map omits, a deleted line for an existing file, and a
drawn path that does not exist.

Two details worth keeping:

- The guard reads `git ls-files`, not `git ls-tree HEAD`. With `ls-tree` a new
  file is invisible until the commit **after** the one that added it, so the
  planting passed and the guard looked correct. The index is the right source
  because pre-commit runs before the commit exists.
- The first reverse guard scanned every backticked path in the file and
  reported ten deletions, **none of them defects**: `api/ws/` and
  `core/llm/keyring.py` appear in the structure changelog, whose entries read
  "Deleted `api/ws/`". A changelog naming things that are gone is a changelog
  working. Scoped to the folder-map tree instead.

And the prose was corrected rather than the guard widened where the wider claim
was not one worth enforcing: sixty-one nested directories are described by
pattern, not individually, so ARCHITECTURE now says top-level and says why.
**When prose and mechanism disagree, one of them is wrong - decide which, do
not split the difference.**

## How the audit was run

For each guard: mutate the repository so the invariant is genuinely broken, run
that guard alone, record the exit code, revert with `git checkout`/`git clean`,
and confirm it returns to green.

Six guards initially reported as never-failing. **Investigation showed five were
faults in the audit harness, not the guards** — the mutation helper used
`str.replace(old, new, 1)`, and in five cases the first occurrence of the anchor
was inside a *docstring* rather than the code, so the mutation never touched the
mechanism. Corrected mutations made all five fail properly.

That is worth recording, because a bad audit is the same trap one level up: it
reported success while testing nothing.

## Limits of this audit, stated plainly

- **One mutation per guard.** A guard that survives its planted violation may
  still be blind to a *different* one. Mutation testing bounds confidence; it
  does not establish correctness.
- **Behaviour is not proved.** `test_chart_has_a_validation_template_that_fails_closed`
  checks that `fail()` calls exist, not that Helm refuses to render. The
  behavioural proof lives in `ci-deploy.yml`, which runs `helm template` against
  `values-prod.yaml` with a credential removed and requires it to fail.
- **This is a snapshot.** A guard changed after this date is unverified until
  someone plants a violation against it again.

## The two "delivery failures" that were not, 2026-08-19

The alert gate sat at 5 of 8 with two failures reported as Alertmanager not
receiving what Prometheus sent. The message read *"the alert fired in
Prometheus but never reached Alertmanager"* - a sentence asserting the first
half while testing neither.

Sampling both endpoints together during a real run settled it in one pass:

```
t=326.1  prom=[CheckoutErrorRateHigh]  am=[CheckoutErrorRateHigh]   <- same 2s sample
t=350.7  prom=[CheckoutErrorRateHigh]  am=[CheckoutErrorRateHigh]
t=361.0  prom=[]                       am=[]                        <- ~5s after the run
```

**Delivery was never broken.** Alertmanager holds the alert in the same
two-second sample Prometheus starts firing it. Both tests polled Alertmanager
*after* the run returned, by which time the alert had resolved and been dropped.

This is the defect already recorded on this page under *"a gate that asserts
after the run tests retained state"* - fixed for the scenario tests on this
same branch, and never carried across to these two. **Fixing one instance of a
class and leaving another, twice on one branch.** The first pair was memory and
latency; this pair is the two delivery gates.

A second defect the same run exposed: the label test ran no scenario at all. It
read Alertmanager directly and depended on the test above it having just left
the alert there - so it would fail standalone even with delivery working, and
passed for the wrong reason whenever ordering happened to suit it. It now runs
its own scenario.

> **A failure message that asserts half the chain hides which half broke.**
> "Fired in Prometheus but never reached Alertmanager" named a culprit for a
> run that had checked neither end. Assert each hop you name.

## Two rules the claim audit produced, 2026-08-19

### A sentence in the present tense about a test reads as a fact

The audit found eight claims describing mechanisms that did not exist. The
costliest said the repository map **"cannot go stale without a test failing"**
- present tense, stated as fact, in the most-read file in the repository. Three
files were committed without appearing in the map across three commits, every
run green.

Such a sentence is checkable in seconds and is among the least likely things in
a repository to be checked, precisely because it does not read like a claim.
"A guard asserts X" invites belief the way "we should assert X" does not.

> **Any sentence asserting a mechanism must name the test that enforces it, or
> be rewritten as intent rather than fact.** "`test_x` asserts X" is checkable
> by one grep. "X is guarded" is a belief with no address.

The nine claims in this repository that named a test all resolved to a real
one. Every false claim was in the set that named none. That correlation is the
whole argument: naming the test is not decoration, it is what makes the claim
falsifiable.

### Plant in the conditions the guard runs in

The fourth too-narrow scanner, and the nastiest, because **the planting passed**.

The map-currency guard read `git ls-tree HEAD`. Planting a new file the map
omitted did not fail it: `ls-tree HEAD` reads the last commit, so a staged file
is invisible until the commit *after* the one that added it. The guard looked
verified while being blind to the exact moment it runs - pre-commit, before the
commit exists. Switching to `git ls-files` made the same planting fail.

The three earlier cases were scanners too narrow for a *syntactic* form. This
one was narrow for a *temporal* one, which no amount of reading the regex would
have shown.

> **Plant in the conditions the guard runs in, not only the conditions
> convenient to test.** A hook runs pre-commit, CI runs post-push, a scanner
> runs against rendered output. If the planting does not reproduce that
> context, a green planting is evidence about the test harness and silence
> about the guard.
## A rejection is only evidence if the reason is the one you tested for, 2026-08-19

Branch protection on `develop` was verified **behaviourally** rather than by
reading the settings page: a direct push, and read the refusal.

The first attempt was rejected with **non-fast-forward**. That is ordinary git
behaviour on a stale ref and would have happened with no ruleset at all. Taking
it as proof would have been the same mistake as a guard that passes for the
wrong reason - a red result, obtained, and about something else entirely.

The push that proved it was rejected with **GH013**, citing the pull-request
requirement and the required status checks by name. That refusal can only come
from the rule being tested for.

> **A failing result is evidence only when its reason is the one under test.**
> "It was rejected" is not a verification; "it was rejected *because of the rule
> I am testing*" is. Read the error, not the exit code.

This is the same class as every other entry here. A guard that fires for an
unrelated reason, a scanner that exits 1 because it crashed rather than because
it found something, a threshold that fails the build on findings it never
claimed to gate - each looks like the mechanism working.

The verified state on `develop`: `pull_request` and `required_status_checks`
requiring the context `CI`, plus `deletion` and `non_fast_forward`. The required
check name matches the job `ci.yml` reports, which is the detail that makes the
rule bite rather than block forever on a check that never arrives.
## Three of four shapes did nothing, 2026-08-19

`shape: ramp`, `shape: spike` and `shape: sawtooth` were declared across five
scenarios. **Only `step` ever worked.**

`Scenario.phases_at` decided a phase was running by comparing
`simulated_seconds - baseline_seconds` against the phase bounds.
`MetricsGenerator.sample` then computed how far through it was as
`(simulated_seconds - phase.start_seconds) / duration` - from **absolute**
time, against a **baseline-relative** start. Absolute time is never less than
`baseline_seconds`, so progress never fell inside [0, 1]: measured through
`memory_leak`'s leak it ran **2.18 to 3.18** and clamped to 1.0 throughout.

At progress 1.0 the shape factors are:

| shape | factor | effect |
|---|---|---|
| `step` | 1.0 | correct, by accident |
| `ramp` | 1.0 | never ramps - identical to `step` |
| `spike` | `sin(pi)**0.5` = **0.0** | **inert** |
| `sawtooth` | `(4.0) % 1` = **0.0** | **inert** |

So `memory_leak`'s OOM sawtooth and `disk_pressure`'s eviction spike changed
nothing at all, and every ramp was a step. Fixed by returning progress *with*
the phase from one method, `Scenario.active_at`, so activity and progress
cannot be measured from different origins - the same computation had been
written in three places against two origins.

### The two failure modes compound, and the result looks doubly verified

A guard existed. `test_a_deviation_is_absent_before_its_phase_begins` asserted
`_apply(10.0, Deviation(factor=9.0), 0.0) == 10.0`, and passed for two
independent reasons:

- **Wrong layer.** `_apply` is *handed* a progress. Whether a phase is running,
  and what progress it is at, are decided by its caller. Testing `_apply` proved
  a helper multiplies correctly and said nothing about the argument it is given.
- **One form planted.** At progress 0.0 a `ramp` contributes nothing, so the
  default shape passed. `step` returns 1.0 whatever the progress and would have
  failed the same line.

> **Two weak guards in one test read as one strong guard.** Each flaw alone
> leaves something visibly untested. Together they produce an assertion that
> names the right behaviour, sits in the right file, and cannot observe the
> defect from either direction - so nothing about it looks wrong. This is the
> fifth too-narrow scanner and the second wrong-layer guard, and the first time
> both have appeared in one test.

Replaced with three guards, each planted: absence before the phase (**every**
shape, driven through `sample`, on a scenario built for the purpose); every
shape moving the metric *somewhere* in its phase, which is what catches an
inert one; and progress staying inside [0, 1) across a **real** scenario, which
is the only one that can see the origin defect - a fixture phase starting at
zero makes the two origins agree, which is why every existing fixture missed it.

A fourth guard was needed for `_node_disk`, the second site that recomputed
progress. Planting there failed twice before it fired: monotonic climb does not
separate the states, because the drift term rises either way. The signature is
the *shape* of the climb - a ramp gains 0.445, 0.445, 0.445 of its first
reading per step; the defect gains 0.102, 0.0001, 0.0001.

### An error message that asserts a cause is a claim

The alert gate failed with *"the alert fired in Prometheus but never reached
Alertmanager"* on a run that had checked neither end. Delivery was fine; the
gate was looking after the alert resolved. The message named a culprit, was
believed, and pointed the investigation at the wrong component.

> **An error message that asserts a cause needs the same evidence as any other
> claim.** Say what was observed - "expected X in Alertmanager, saw []" - not
> what it implies about a component the assertion never queried. This is the
> same failure as present-tense prose about tests: a sentence that reads as a
> finding when it is a guess.

## The destructive part is invisible in the verb, 2026-08-19

Verifying `main`'s ruleset needed a commit to push and have rejected. The probe
was set up with:

```bash
git checkout -B tmp/protection-probe origin/main   # DON'T
```

`-B` does not mean "branch". It means **reset the branch to this commit,
creating it if absent**. Local branch state was rewritten as a side effect, and
`docs/readme-front-door` was later found sitting at `Initial commit`, 132
commits behind its remote, with the uncommitted work on it gone. The remote was
untouched, so recovery was `git reset --hard origin/<branch>` - but the
uncommitted half was not recoverable and had to be rebuilt.

The correct form for a probe that needs a throwaway state:

```bash
git checkout --detach origin/main                  # cannot rewrite a ref
```

> **A flag that rewrites history can read as a convenience.** `-B` looks like
> `-b`. `reset --hard` on the wrong branch looks like tidying. The destructive
> part is not in the verb - `checkout` and `reset` both sound navigational - so
> it cannot be caught by reading the command as English. Check what the flag
> *writes*, not what the command is called.

Two habits follow, and both are already rules here for other reasons:

- **Never chain anything behind a destructive command**, which the pre-merge
  ritual already says about merges. The probe chained `-B` behind nothing and
  still cost work, so the rule is about the command, not the chain.
- **Verify with a read before acting.** `git branch -v` before and after would
  have shown the rewritten ref immediately. The same reset scare was raised
  from the other side minutes later and dissolved in one `git rev-parse`
  comparison: local and remote identical on every branch, nothing lost.

The second is the more general lesson. **A suspected loss and a real one look
identical until something is read.** One was real and silent; one was reported
and false. Neither was settled by reasoning about what the command should have
done.

## No in-process assertion could have caught it, 2026-08-19

The concrete case for *plant in the conditions the guard runs in*.

`simulator/metrics_generator.py` opened with a DETERMINISM note: *"The generator
is seeded per pod and metric, so two runs of the same scenario produce the same
series. A scenario that behaves differently each run cannot be ground truth."*
`_seed` was:

```python
return abs(hash("::".join(parts))) % (2**32)
```

Python randomises `hash()` for `str` **per process** unless `PYTHONHASHSEED` is
set. Every run produced a different series. Two runs of one measurement of
`noisy_neighbor` differed by 70% in peak latency - 0.7487 against 1.2345 - and
one rule flipped from passing to failing between them.

> **Within one interpreter, `hash()` is perfectly stable.** A same-process test
> of `_seed` passes whatever it does. The defect exists only in the boundary
> between runs, so a guard that never crosses that boundary cannot see it, no
> matter how carefully it is written.

`test_the_generator_is_deterministic_across_processes` spawns two real
subprocesses and compares a digest of the same series. Planted two ways: the
original `hash()` restored, and a subtler variant where the seed is stable but
the per-metric phase shift still routes through `hash()`. Both fail; the fixed
code passes.

The two hash seeds are set explicitly to `1` and `2` rather than left to the
interpreter. Left to chance, two runs draw random seeds that can coincide, and
the guard would pass for the wrong reason at some low rate - a flake that reads
as a pass, which is the failure mode this whole document exists for.

The fix is a stable hash in the code, **not** `PYTHONHASHSEED=0` in the
environment. An env pin moves the property out of the module: anyone importing
it from a notebook or a REPL gets non-determinism back, and the guarantee then
depends on how the process was launched rather than on what the code says.

This was the ninth false mechanism claim found, and the first found by
**measuring** rather than by reading. The audit sweeps for claims naming no
test; this one named no test and was also invisible to inspection, because the
code looks correct and the docstring describes what it intends.

## A measurement aimed at the wrong subject, 2026-08-19

While measuring the five alert thresholds, `memory_leak`'s self-relative memory
rule was measured against `checkout` pods. The scenario targets **`search`**.

The result: *"baseline max 1.156, fault max 1.156 - no usable threshold at any
offset"*, reported as a finding that the rule could not work. It was measuring
pure baseline. Against the pods the fault actually touches, the ratio peaks at
**3.38** against a baseline of 1.16, and the existing threshold sustains three
times longer than it needs to. The rule was never in trouble.

> **A measurement aimed at the wrong subject returns a real number about the
> wrong thing.** It has the shape of a result - plausible magnitude, consistent
> across parameters, no error - so nothing about it looks wrong. Confirm what
> the instrument is pointed at before believing what it says.

The tell, in hindsight, was that baseline max and fault max were **identical to
three decimals** across five different offsets. Identical numbers where a fault
should have moved one of them is a signal about the instrument, not the system.

This is the fourth time the instrument rather than the code was the defect,
after the audit's `replace(..., 1)` stopping at the first occurrence, the
phase-window diagnostic that bypassed `phases_at` and invented a defect that
did not exist, and the connector gate whose five-minute window could not see a
fault lasting one. **The instrument is code too, and nothing checks it.**

## Right for reasons you did not have, 2026-08-20

Before the simulator's determinism was fixed, the prediction was *"expect more
than flaky_test_storm to move"*. Then a measurement said the other four had
margin, and it was retracted on that evidence. With the generator producing a
stable series, **two** rules moved - the original prediction was right.

It does not count. The retraction rested on measurements that flipped
`noisy_neighbor` between 11.4s and 7.0s across two runs of the same script;
the re-assertion rested on measurements that reproduce exactly. Same
conclusion, different epistemic status.

> **A prediction that turns out right for reasons you did not have is not a
> correct prediction.** Grade the reasoning, not the outcome. Otherwise the
> lesson recorded is "trust the hunch", when the actual lesson is "the
> instrument was broken and every number it produced was noise".

Same family as the two already on this page: a push rejected for
non-fast-forward rather than the ruleset under test, and a scanner exiting 1
because it crashed rather than because it found something. In all three the
**result** is what was expected and the **reason** is not the one claimed, and
only the reason makes it evidence.

## Identical numbers where a change was expected, 2026-08-20

Worth its own heuristic, because it is cheap and it fires early.

Measuring `memory_leak` produced this, across five different look-back offsets:

```
offset  10s: baseline max 1.065  fault max 1.065
offset  20s: baseline max 1.121  fault max 1.121
offset  30s: baseline max 1.156  fault max 1.156
offset  45s: baseline max 1.175  fault max 1.175
offset  60s: baseline max 1.152  fault max 1.152
```

Baseline and fault agreeing **to three decimals, five times**, was read as
"this rule cannot separate the fault from the daily cycle" and reported as a
finding. It meant the measurement was sampling `checkout` while the scenario
faults `search`: both columns were the same clean series.

> **A fault that moves nothing has either no effect, or is not being observed -
> and the second is far more likely.** Identical numbers where a change was
> expected is a signal about the instrument. Check what it is pointed at before
> believing what it says.

The reason it is worth a rule of its own: a *wrong* number invites suspicion,
but an *unchanged* number reads as a finding - "no effect" is a legitimate
result, so nothing about it looks like an error. That is what made it costly
here, and it is the same reason a guard that cannot fail looks like a guard
that passes.

## Five green hooks over a file that was not valid Markdown, 2026-08-20

A merge commit went in with `README.md` and `ARCHITECTURE.md` unresolved. The
README's status table held both the pre-rewrite layout and the front-door one,
joined by `<<<<<<<` / `=======` / `>>>>>>>`, and the commit succeeded.

Every hook passed:

```
ruff check ..... Passed      mypy (strict) ..... Passed
ruff format .... Passed      gitleaks .......... Passed
                             codegen drift ..... Passed
```

None of them reads Markdown. ruff and mypy are Python-only, gitleaks looks for
credential shapes, and codegen-verify diffs generated output. The file was not
valid Markdown - it was two documents spliced by conflict markers - and five
checks reported success on it.

> **A green hook run means the hooks that ran passed.** It says nothing about
> the file types none of them inspect. Coverage is not the number of checks; it
> is which inputs any check reads at all.

Fixed with `check-merge-conflict` placed **first**, because every hook below it
is meaningless on a file that still has markers in it. Planted both ways: a
conflict block in `README.md` fails it, removing it passes.

### What else nothing reads

The obvious follow-up, since one hole of this shape implies others. Of 41
tracked `.json`, `.toml`, `.sh` and `.tf` files, **34 are named by no test**,
and no hook validates their syntax:

| type | tracked | inspected by a hook | named by a test |
|---|---|---|---|
| `.py` | 224 | ruff, ruff-format, mypy | many |
| `.tf` | 28 | none | **0 of 28** |
| `.sh` | 7 | none | 3 (the codegen scripts) |
| `.json` | 4 | none | 2 |
| `.toml` | 2 | none | 2 |

`.yaml`/`.yml` sit in between: no hook parses them, but tests do - workflows in
`test_ci_workflows.py` and deploy manifests in `test_every_deploy_manifest_parses`.
Helm templates are excluded there because they are Go templates rather than
YAML until rendered, so they are covered only by `helm lint` in CI.

The Terraform tree is the largest gap: 28 files, no hook, no test, and
`terraform fmt`/`validate` run only in `ci-deploy`. That is later than
pre-commit but it is not nothing, which is why this is reported rather than
fixed - the shape of the hole matters more than plugging it today.

## One missing question, asked four times, 2026-08-20

Four defects stood between `flaky_test_storm` and firing. They are recorded
together because they were not four independent misses: **each one produced the
conditions that let the next pass.**

**1. Nobody chose an aggregation.** `ci_failures.labels(pod.service, CLUSTER)`
sat inside `for pod in PODS`, so three checkout pods wrote one series and the
last in iteration order won. The other two samples were computed and discarded.
The labels were right and the value was plausible, so nothing looked wrong -
but the series was an artifact of list order rather than a decision.

**2. The offline measurement took a `max` across pods.** Reasonable-looking,
and it measured **a value the system never published**. It matched the live
series closely by coincidence: the last pod in order happened to be the
highest, so `last == max` and the numbers agreed for the wrong reason.

**3. A threshold was derived from that max and shipped.** `0.12`, written into
`rules.sim.yml` with its measurements beside it. Every number in that comment
was real. All of them described a series that did not exist.

**4. The headroom guard blessed a ratio it called a margin.**
`BUDGET_FRACTION = 0.5` let a rule use half the visible fault, which for a 10s
rule is exactly two evaluation intervals. `test_every_rule_can_fire_within_its
_scenarios_fault_window` enforced that inequality and reported it as headroom.
Both faces showed in one run: `noisy_neighbor` and `flaky_test_storm` had
identical two-interval headroom, one fired and one did not.

Four checks in sequence. Each passed. Each passed **because of the one before
it**: the aggregation bug produced a series nobody had chosen, the measurement
described that unchosen series, the threshold inherited the measurement, and
the guard certified the speed at which none of it could hold.

> **A defect chain is not four independent misses. It is one missing question
> asked four times.** The question was *"what value does this actually
> produce?"* - and nothing asked it until the live gate ran.

That is the argument for the empirical gate in one line. Every offline artifact
here was internally consistent: the code type-checked, the measurement
reproduced exactly across runs, the threshold had its evidence written beside
it, and the guard enforced a stated rule. Consistency propagated the error
rather than catching it, because all four were reading the same wrong series.
Only running the thing against a real Prometheus asked what came out the far
end.

The corresponding guards now ask that question at four points: the emission is
structurally forbidden from depending on iteration order, the aggregation is
asserted to be the mean, the headroom floor is derived from measured duty
cycle, and the gate itself watches Alertmanager during the run rather than
after. Each planted in both directions.

## A constant read as a trend, 2026-08-20

Distinct from measuring the wrong subject, and worth separating: **the number
was real, and the pattern was imposed on it.**

Loki's push endpoint started returning 500. Its log showed:

```
msg="checkpoint done" time=4m30.107457737s
```

Four and a half minutes for a WAL checkpoint reads as pathological, and the
next step was going to be "checkpoints are growing and starving the
heartbeat". Printing the column killed it:

```
11:05:36  4m30.014281535s      12:55:35  4m30.086528312s
11:10:36  4m30.016202610s      13:00:35  4m30.090265305s
11:15:36  4m30.021941609s      13:15:35  4m30.107457737s
```

Constant to three decimal places, across healthy periods and unhealthy ones
alike. It is a **paced cycle**, not accumulating work, and it had been 4m30
since before anything went wrong.

> **Before reading a trend, check the column varies.** A fixed interval and
> accumulating work look identical in the last few rows, and the last few rows
> are what a `tail` shows you. One value repeated is not a slow rise.

The real signal was in what the log did **not** contain: gaps. Nothing at all
between 13:15:35 and 13:41:07, and an earlier silence from 11:26:20 to
12:25:35. Loki was not slow, it was frozen - and the actual cause was that it
had aged its **own** ring entry out (`unhealthy instances: 127.0.0.1:9095`, its
own address) after its heartbeat stalled, leaving the distributor with zero
healthy ingesters.

Both hypotheses on the way there were wrong, and each was discarded by looking
rather than by reasoning: "Loki stopped logging" (misread clock) and
"checkpoints are growing" (constant column).

## A test that exercised more than its subject, 2026-08-20

The unit under test was the runner's *handling* of a rejected log push. The
first version pointed it at a closed loopback port to provoke the rejection.

It hung the suite past 600 seconds. Windows does not refuse a connection to a
dead loopback port promptly, so three hundred ticks of connect-and-wait never
finished. The test was measuring Windows' connection-refusal timing, which is
not the subject and not a property this repository cares about.

Rewritten to raise `httpx.HTTPStatusError` from a patched sink: 4.3 seconds,
and it fails for exactly one reason.

> **A test that exercises more than its subject fails for reasons unrelated to
> its subject** - and passes for unrelated reasons too. Reach for a real socket
> when the socket is what is being tested.

## Reproducibility is not coverage, 2026-08-20

Ten baseline-only runs against the live stack, to bound the false-positive rate
for Argus. Every run completed, none degraded, and the numbers were tight:

```
error_ratio   max 2.63   median 2.53   across runs: 2.6 2.6 2.5 2.3 2.6 2.5 2.5 2.3 2.3 2.5
latency       max 4.35   median 4.07
ci_ratio      max 4.53   median 4.24
highest |z| on any clean baseline: 4.53
```

A threshold of 6 clears that comfortably. It would have been wrong.

The *pre-fault* windows of the scenario sweep are also clean baseline, and on
the same metric they reach **15.67** - six times the bound ten reproducible
runs had just produced. A `Z_THRESHOLD` of 6 would have false-positived on
`error_ratio` immediately.

> **Reproducibility is not coverage.** A tight distribution measures the
> conditions you sampled and says nothing about the ones you did not. Ten runs
> agreeing to two decimal places is evidence that the measurement is stable,
> not that the space is mapped - and the tightness is what makes it look
> authoritative.

This is a different failure from the instrument defects already on this page.
There the instrument was broken - the wrong pods, a `max` across a series that
was never published, a generator producing different data every run. Here **the
instrument was correct**. Every number was real, the method was sound, and the
sampling was too narrow. Nothing about the output could have revealed that.

### The tell, and why it was worth chasing

The obvious explanation was warm-up: `rate()` over a counter freshly reset by
the pushgateway is unstable, so an early excursion would be an artefact rather
than a property. Locating the excursions killed it:

```
noisy_neighbor    pre-fault 480s   worst |z| = 15.67  at t=220s
bad_deploy_5xx    pre-fault 379s   worst |z| =  6.76  at t=331s
flaky_test_storm  pre-fault 137s   worst |z| = 14.80  at t=137s
```

Mid-window, not at the start.

> **A discrepancy that survives the obvious explanation is a difference in
> condition, not noise.** The cheap explanation is worth testing precisely
> because rejecting it promotes the discrepancy from "probably nothing" to
> "something varies that I have not identified".

Two samples from an unmapped space are not a bound, so neither 2.63 nor 15.67
is one. The candidates - compression speed, window duration, which services
were covered - are being varied one at a time before any threshold is set.

## The ground truth can have artifacts the real system does not, 2026-08-20

The most dangerous instrument defect on this page, because the instrument is
supposed to be authoritative.

`error_ratio`'s clean-baseline |z| was isolated to a beat between the
simulator's push tick and Prometheus's scrape interval: 0.76, 2.10 and 8.33
ticks per scrape at 228x, 630x and 2500x, with the worst noise just past two.
The analysis was right, and it leads somewhere other than a threshold.

**That beat exists only because of compression.** The push tick scales with
speed; the scrape does not. Nothing on a real cluster pushes at eight times the
scrape rate. So a threshold calibrated against this noise floor would be
calibrated against a phenomenon Argus will never meet in production - and it
would look, in every artifact downstream, exactly like a property of the data.

> **An artifact in the ground-truth generator propagates as truth.** Thresholds
> are derived from it, Findings are judged against it, and agent scoring will
> eventually be graded on it. Every one of those inherits the artifact wearing
> the appearance of a measured property, because the generator is the thing
> everything else is checked against.

The earlier instrument defects on this page were *visible* once looked for: the
wrong pods, a `max` over a series never published, a non-deterministic seed.
This one produces correct, reproducible, internally consistent measurements of
something that is not real.

So the generator is fixed rather than the artifact characterised: the push
cadence is decoupled from compression, ticking on a fixed wall schedule and
advancing simulated time per tick instead. Characterising the artifact would
have produced a defensible number, derived live, reproducible across runs, and
wrong for production - the one failure mode none of the existing rules on this
page would have caught.

**Stated as a limitation regardless of how it resolves:** thresholds derived
under compression may not transfer to an uncompressed cluster. That does not
invalidate simulator-derived calibration, but a reader must not take these
numbers as production-ready.

## Procedure: enumerate the forms before writing the matcher

Not an observation - a step to perform. This has now produced four defects, all
the same shape, so it is written as something to do rather than something to
remember.

The four:

| matcher | form it missed |
|---|---|
| `.PHONY` completeness | a backslash continuation, so it never read the second line |
| the raw-read sweep | `.read_bytes()`, while `read_text()` and `open()` were covered |
| the step-event guard | `from X import Y`, having walked `Name` and `Attribute` nodes only |
| the counted-noun guard | `Decision Records` against a case-sensitive `decision records` |

Each was written by looking at the example in front of it and describing that.
Each then matched exactly the example in front of it. Calling this an attention
lapse four times has not stopped it, because it is not one - **a matcher shaped
by its first example is a design method, and it produces this result reliably.**

### The same procedure, for scenarios

Third instance of one mistake, now with a measurable consequence.

| occasion | what was assumed | what the target said |
|---|---|---|
| measuring `memory_leak` | it targets `checkout` | it targets `search` - the measurement read pure baseline and reported "no usable threshold at any offset" |
| classifying `disk_pressure` | cluster-wide disk fill | it targets `node-a` - predicted as the at-risk common-mode case, it was the strongest divergence signal |
| classifying `noisy_neighbor` | one node diverging from its peers | `node-c` is **4 of 12 pods**, so at pod level it is partial common-mode - the failure mode was predicted correctly and assigned to the wrong scenario |

Each time the scenario's *description* was read and its *target set* was not.
The descriptions are accurate; they describe the fault in the operator's terms,
and the peer comparison happens at a different granularity than the words.

> **Before measuring a scenario, write down its phase targets as data** - which
> pods, which services, what fraction of each peer group. `pods_for(phase.target)`
> answers it in one line. The description tells you what the fault *means*; only
> the target set tells you what the measurement will *see*.

The same shape as enumerating a matcher's forms before writing it: the
enumeration is the design step, and skipping it lets the first plausible reading
choose the answer.

### The step

**Before writing the matcher, write down the forms it must catch, as test data.
Then write the matcher against that list.** The enumeration is the design; the
regex or AST walk is the implementation. Doing them in the other order lets the
first example choose the shape.

Prompts for the enumeration, from the four above:

- **Case** - `MAD`, `mad`, `Mad`. Is the input source-controlled or prose?
- **Import and reference** - `import x`, `from x import y`, `x.y`, an alias.
- **Whitespace and continuation** - a line break, a backslash, a wrapped list.
- **Plural and singular** - `test`/`tests`, `record`/`records`.
- **Synonyms for the same call** - `read_text`, `read_bytes`, `open().read()`.
- **Negation and absence** - does the guard need to fire when something is
  *missing*, and can it see a missing thing at all?

Then plant **each enumerated form**. One green planting on a multi-form rule is
evidence about one form and silence about the rest - which is already on this
page, and is what this procedure operationalises.

The cost is a few minutes per guard. The alternative is measured: four guards
that read as complete, passed continuously, and were blind to the case that
mattered.

## A mechanism fitted to the points that suggested it, 2026-08-20

**Both of us believed this one**, which is why it is filed as a rule rather
than as an error. The maintainer endorsed the mechanism and directed a
generator change on the strength of it; the agent produced the three-point fit
that made it convincing. Neither pushed on it, because the arithmetic was real
and the correlation was exact.

`error_ratio`'s clean-baseline |z| measured 2.42, 18.18 and 4.71 at 228x, 630x
and 2500x. The push tick against the 1s scrape gives 0.76, 2.10 and 8.33 ticks
per scrape at those speeds. A beat between tick and scrape explains a
non-monotonic noise floor peaking just past two ticks per scrape, and every
number lined up.

It was wrong. Holding the cadence fixed at 8 pushes per scrape - which removes
the beat entirely - left the spike **higher**: 20.22 at 630x against 15.16
unpaced, with 228x and 2500x unchanged.

> **A mechanism fitted to the points that suggested it explains nothing until
> it predicts a point it has not seen.** Three points and a plausible story
> will always agree; that agreement is what the story was built from. The test
> is a prediction that can come back no.

### What a real test looked like

The replacement hypothesis - that the window spans a fraction of the diurnal
cycle, worst near two-thirds - was written down **with numbers, before the
run**, in a committed file:

| fraction | predicted | measured |
|---|---|---|
| 0.25 | 3 - 8 | **11.10** |
| 0.50 | 10 - 18 | 18.43 |
| 0.66 | 18 - 25 | 22.14 |
| 1.00 | 3 - 8 | 6.57 |
| 2.00 | 2 - 6 | 5.89 |

Two further predictions were made specifically because they could fail
independently of the first, and one of them did - see the entry below.

The value of predicting first is not that it makes you right. It is that
"11.10 where 3-8 was predicted" is a visible miss, where a number read after
the fact would have been absorbed into the story without anyone noticing.

## A test written to confirm a property failed, and was right, 2026-08-21

The first time in this branch that a **test** rather than a measurement
corrected a design belief, and it found a parameter nobody had noticed existed.

`test_peer_z_cancels_a_common_mode_shift` was written to pin the property the
whole peer-relative approach rests on: seasonality moves every peer together,
so a uniform shift must not change the comparison. It was expected to pass on
the first run. It failed.

The scale floor was `min(|value|) * 1e-3` - derived from the data's own
magnitude. When MAD collapses to zero the floor becomes the scale, and a floor
proportional to the level makes z level-dependent. **Common-mode cancellation
broke precisely where the estimator was already degenerate**, which is the worst
place for it to break and the least likely place to look.

### The floor was a third parameter, undeclared

`WINDOW_SECONDS` and the threshold were both derived, argued for, and stated.
The floor sat inside the estimator as a heuristic, was never measured, and was
invisible in every result it produced - while being capable of deciding the
answer outright.

It already had: `disk_ratio` over three nodes produced **1599.63 on a clean
baseline** in one scenario and **1585.74 as a signal** in another. Both were the
floor speaking. One of them was reported as the strongest detection in the
branch before the degeneracy was understood.

> **A parameter that can determine the output is a parameter, whatever it is
> called.** "Floor", "epsilon", "guard value", "small constant" - if the result
> changes when it changes, it needs deriving, stating and refusing like any
> other. A number small enough to look harmless is the easiest kind to leave
> underived.

Now: `SCALE_FLOORS` is per metric and empty, `floor_for` refuses rather than
substituting, and `PeerComparison.floor_engaged` travels with every reading, as
does `MetricWindowPayload.scale_floor_engaged` through codegen. **A number whose
provenance is the floor must not be indistinguishable from one whose provenance
is the distribution.**

Declaring it also fixed the defect that exposed it. A constant floor does not
move with the data, so cancellation now holds in both regimes - and the test is
kept, inverted, because a future floor derived from the samples would fail it
again.

## A status code is not evidence of an effect, 2026-08-21

The most transferable entry on this page, and the one that hid the longest.

Every reset in this repository deleted the pushgateway group `pantheon_sim`.
The generator pushes to `pantheon-sim`. **A pushgateway returns 202 Accepted for
a group that does not exist**, so every reset succeeded loudly and cleared
nothing - for a week, in every calibration harness, and in the integration gate
that was merged as 8/8 green.

Measured directly:

```
DELETE /metrics/job/pantheon_sim  -> 202   series still served: 119
DELETE /metrics/job/pantheon-sim  -> 202   series still served: 0
```

Same status code. Opposite effects.

> **A status code is evidence that a request was accepted, never that anything
> happened.** Assert the postcondition. A delete that returns 200, a config
> reload that returns OK, a cache flush that reports success, a webhook that
> answers 202 - none of them is evidence the thing occurred, and the ones that
> answer success unconditionally are the ones that hide longest.

`MetricsGenerator.reset()` now deletes and then **queries**, raising
`PushgatewayNotClearedError` if any series is still served. That converts a
silent no-op into a loud failure, and it is what would have caught this on the
first day rather than the seventh.

### Fix the cause, not the instances

The job name was a literal repeated across four callers while
`metrics_generator` used `self.job`. Correcting the three known callers would
have left the fourth to be written next week, so it is now one exported constant
with `tests/unit/test_no_job_name_literals.py` failing the build on any module
that spells it out - **both spellings**, since a guard forbidding only the
correct one would have passed throughout the defect.

The guard immediately found three more occurrences nobody had listed, and
distinguishing them was the useful part: the Loki stream label (now
`LOKI_JOB_LABEL`, named separately because it belongs to a different system and
could legitimately diverge) and the CLI command name (a different concept
sharing a spelling, allowed with the reason recorded).

### A constant used in two directions needs asserting in both

`test_simulator_components.py` asserted the **push** path spelled it
`pantheon-sim`. The **delete** path had no test at all. So the half that was
wrong was the half nobody checked - the same shape as the `satisfies` guard that
caught component removals but not additions, and the tests that iterate *over*
`REQUIRED_IN_PRODUCTION` rather than checking the set is complete.

Two of this entry's own guards were too narrow on the first attempt, both
caught by planting:

- the literal guard reported line numbers computed against comment-stripped
  source, so its locations did not exist in the files;
- the postcondition guard asserted the substring `PushgatewayNotClearedError`
  appeared in the module - which the **class definition** satisfies, so deleting
  the raise from `reset()` left it green. It now walks the AST of `reset` and
  asserts the raise is inside it.

## A commit existing locally and a commit surviving a merge are different facts

`55b0360` was written, committed, and referenced by name in a later document. It
was on `feature/argus`. `develop` was reached by a merge that did not carry it,
and the file stayed in the working tree the whole time - so every local check
that opened it succeeded, and it was one `git branch -D` from gone.

"I committed it" is a claim about a local object. What matters is whether the
branch contains it, and those come apart silently, because deleting a branch
removes the only reference to the commit while leaving the file on disk
untouched.

The recovery was a cherry-pick. The guard is
`tests/unit/test_prediction_records.py`, which compares what is **tracked by
git** against what is present on disk, rather than checking that files exist:

```python
tracked = set(subprocess.run(["git", "ls-files", "docs/argus-predictions"], ...))
on_disk = {p.relative_to(REPO_ROOT).as_posix() for p in PREDICTIONS.rglob("*") if p.is_file()}
assert not (on_disk - tracked)
```

Verified against five planted violations, each fixed before the next:
untracking a file; removing a `# Result` section; deleting a record so the index
disagrees; deleting a record **and tidying the index to match** (caught by the
numbering gap, which the tidied index cannot hide); and removing a cited
measurement. All five failed. The first plant also found four real gaps - three
prediction files scored only in conversation, never in the repo.

### Plant against committed state, not against uncommitted work

The plantings were run before committing the scorings, and `git checkout --
docs/argus-predictions/` between plants reverted three files of real work that
happened to be unstaged. Nothing was lost that could not be retyped, which is
luck rather than process. Commit first, then plant: the restore step of a
planting is destructive by design and cannot distinguish your plant from your
work.

## The rule

> When you add or change a guard, plant a violation and watch it fail. If you
> have not seen it red, you have not tested it.
>
> And when a guard fires, fix the code. Narrowing the guard to make it pass
> converts a real finding into a permanent blind spot.
>
> Plant it in the conditions it will actually run in, and make every sentence
> claiming it exists name it.

_Phase: 0 - Scaffold & Tooling_
