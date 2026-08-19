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

## The rule

> When you add or change a guard, plant a violation and watch it fail. If you
> have not seen it red, you have not tested it.
>
> And when a guard fires, fix the code. Narrowing the guard to make it pass
> converts a real finding into a permanent blind spot.

_Phase: 0 - Scaffold & Tooling_
