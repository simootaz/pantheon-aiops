# The clock rule, rewritten — 2026-08-27

## No prediction was committed before this run, and that is deliberate

Every other record here commits numbers first. This one does not, because the
change was not decided by this data.

It was decided by a **planted violation in a unit test**: deleting the ordering
rule entirely produced no failure. The rule was rewritten until the plant went
red, and only then was the measurement re-run — as a check that nothing had
regressed on real logs, not as the thing that chose the rule.

Committing a prediction for a confirmation run would be theatre. What follows is
a scoring of the change, and the numbers are reported whether they flatter it
or not.

## The defect two plants and one live run had already shown

`MAX_STABLE_VALUES = 8` masks any field with **nine or more** distinct values.
`MIN_ORDER_CHANGES = 8` needed **nine or more** distinct values before a
monotone clock produced enough changes to judge.

The two rules met exactly. A clock with two to eight distinct values fell
through both, and every template kept its timestamp.

That is not hypothetical. Round 4 of [record 01](01-template-recovery.md)
regressed on a run whose window held three distinct stamps, and I patched around
it rather than seeing the boundary. The unit test made it unmissable: six
stamps, and deleting the rule changed nothing.

Two fixture bugs surfaced with it, and both are the same family as the rule's:

* The sorting test **reversed** the lines. The old rule accepted a field moving
  consistently in either direction, so a reversed clock is still a clock, and
  the test passed against an agent with the sort removed. It now hands back
  thirty streams each in backward order — the shape Loki actually returns.
* The clock test used twelve stamps, then six. `compare()` learns one
  classification over **both** windows, so two windows of six disjoint stamps
  pool to twelve and the cardinality cap masked the clock on its own. The
  fixture was testing the cap while claiming to test the clock.

## The rule now

A field is a sequence when its values form contiguous **blocks** — no value ever
recurs after a different one has appeared. A clock moves on and never returns; a
category comes back.

It needs no direction, no tie handling and no change count, and it does not
depend on values sorting lexicographically, so an unpadded counter where `9`
follows `10` is handled like an ISO timestamp. One parameter remains
(`MIN_ORDER_BLOCKS = 3`), and it exists to exclude a constant (one block) and a
single phase change (two).

## Result — confirmed on real logs, `data/10-block-ordering.json`

| | round 8 (direction rule) | round 10 (block rule) |
|---|---|---|
| templates, both baselines | 62 / 62 | **62 / 62** |
| baseline Jaccard | 1.00 | **1.00** |
| false novelty, clean window | 0 | **0** |
| convergence to the full set | 1.00 at n=1000 | **1.00 at n=500** |
| stack-trace signatures | 1 | **1** |

Novel templates per scenario: `bad_deploy_5xx` 0, `memory_leak` 2,
`disk_pressure` 1, `flaky_test_storm` 0, `noisy_neighbor` 2.

Two of five scenarios report nothing. That is the known blind spot rather than a
regression — `bad_deploy_5xx` multiplies a pattern the baseline already has, and
`flaky_test_storm`'s lines were not in the window the 5000-line cap returned.
Both are recorded in [record 02](02-surprise-and-surge.md) and stated in the
agent's own docstring. **Lethe detects three of five simulator scenarios from
logs, and says so.**

Convergence improving from n=1000 to n=500 was not predicted and is not claimed
as a designed benefit. It follows from fewer fields surviving into templates,
which makes the set smaller and settle sooner.

## What this does not change

The 5000-line cap can still hide a fault. Low-volume events still split on their
variable fields when a group is too small for the block rule to see three of
them. And nothing here gives Lethe a rate test; that still needs a peer axis.
