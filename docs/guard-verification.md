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

## The rule

> When you add or change a guard, plant a violation and watch it fail. If you
> have not seen it red, you have not tested it.
>
> And when a guard fires, fix the code. Narrowing the guard to make it pass
> converts a real finding into a permanent blind spot.

_Phase: 0 - Scaffold & Tooling_
