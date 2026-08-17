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
