# Predictions 11 — MIN_PEERS, third and final time

Written BEFORE the measurement, 2026-08-24, on `feature/argus-min-peers`.

## The question

The same distinction that resolved the pod metrics at T = 10: **does a pooled
bound over N runs make a 5-peer group safe, when a single-run bound does not?**

Both service groups separate their faults comfortably — `error_ratio` at
3331.63 and `ci_ratio` at 950.86 — while `MIN_PEERS = 12` refuses them
unmeasured. The risk is the per-run spread. From 10:

| group | n | pooled T | per-run T | max per-run |
|---|---|---|---|---|
| `memory` | 12 | 4 | 4, 4, 4, 4, 4, 4 | 4 |
| `cpu` | 12 | 4 | 4, 4, 4, 4, 4, 5 | **5** |
| `latency` | 12 | 10 | 8, 10, 6, 10, 10, 8 | 10 |
| `error_ratio` | 5 | 50 | 30, 30, 30, 80, 50, 50 | **80** |
| `ci_ratio` | 5 | 80 | 50, 80, 50, 80, 80, 80 | 80 |

## The criterion this suggests, and why it is not about peer count

A pooled threshold is only safe if it covers the worst run it pooled over.
Pooling averages instants across runs, so **one bad run can be hidden by five
good ones** — the pooled rate stays under target while that run's own rate does
not.

Reading 10's table by that criterion, `pooled T >= max per-run T`:

- `memory` 4 >= 4 and `latency` 10 >= 10 pass;
- `ci_ratio` 80 >= 80 **passes**, at five peers;
- `error_ratio` 50 < 80 fails, at five peers;
- `cpu` 4 < 5 **fails, at twelve peers**.

So the criterion does not sort by group size, which is the first evidence that
the count is the wrong variable — and it comes from data already collected
rather than from this run.

## A measurement artifact to remove first

10's ladder was `4, 5, 6, 8, 10, 12, 15, 20, 30, 50, 80`. It jumps 30 → 50 → 80,
so a "spread of 50" for `error_ratio` is partly the ladder's coarseness rather
than the data's. This run uses `4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25,
30, 35, 40, 50, 60, 70, 80, 90, 100, 120, 150, 200` and reports rates at both
1e-3 and 1e-4.

**Ten runs** at 630x for 480s, timestamps recorded, isolation asserted per run.

---

## P1 — where the pooled thresholds land

> With the finer ladder and ten runs, the pooled T at 1e-3 is **40 – 70** for
> `error_ratio` and **60 – 100** for `ci_ratio`.

**Falsified if** either falls outside its band.

## P2 — the pooled bound converges

> Pooled T computed at N = 2, 4, 6, 8, 10 stops moving by **N = 6** for both
> service groups: no change of more than **one ladder step** between N = 6 and
> N = 10.

**Falsified if** either moves by more than one step after N = 6.

This is the claim that decides whether a threshold can be *stated* at all, and
it is the same shape as P4 in 10, which held for pod metrics.

## P3 — pooling hides a bad run, and not because of peer count

> `pooled T < max per-run T` for **at least one** service group, **and** for at
> least one **12-peer** group as well.

The second half is the load-bearing one. If pooling hides a bad run at twelve
peers too, then the criterion that matters is not how many peers a group has.

**Falsified if** every 12-peer group satisfies `pooled T >= max per-run T` while
a service group does not — which would make the count rule look right for the
first time in three attempts.

## P4 — the practical escape, because the faults are enormous

The service faults are 950.86 and 3331.63. A threshold does not have to sit
near the noise; it only has to sit below the fault.

> A T reaching a pooled rate of **1e-4** exists for both service groups at
> **T <= 200**, and it leaves at least **4x** margin to the scenario fault —
> and that T also clears each group's **worst individual run** at 1e-3.

**Falsified if** no T at or below 200 reaches 1e-4 for either group, or if the T
that does leaves under 4x margin, or if it fails to clear the worst run.

If P4 holds, `MIN_PEERS = 12` as a count is refuted on its own terms: the
groups it refuses are usable, at a threshold their faults clear several times
over.

## P5 — scale stability predicts which groups need a high T

Tying back to 08 and 09, whose statistic replicated at -0.932 and -0.923.

> Rank correlation between `min(scale)/median(scale)` and pooled T, across all
> groups measured here, has magnitude **at least 0.80**, and larger than the
> magnitude for peer count.

**Falsified if** it is below 0.80, or if peer count correlates at least as
strongly.

---

## Stated before the run: what decides the rule

**`MIN_PEERS` becomes a scale-stability property if** P2 holds (a threshold can
be stated), P4 holds (the stated threshold clears the worst run and still
separates the fault), and P3's second half holds (the failure mode is not about
count). The rule then reads:

> A peer group qualifies when a threshold exists that clears its worst observed
> run at the target false-positive rate and still leaves margin to the faults it
> must catch — measured over at least N runs, with N stated.

**`MIN_PEERS` stays at 12 if** P2 fails for either service group — because a
bound that has not converged cannot be written down — or if P4 fails, because a
group whose safe threshold sits above its faults detects nothing.

**`MIN_PEERS` is replaced by a count of runs rather than peers if** P2 holds and
P4 holds but P3's second half fails. That would mean twelve peers really is
sufficient and five is not, and the honest rule is the pair: twelve peers *or*
N runs.

Whatever this resolves scopes the threshold matrix, which lists per-metric
thresholds, their derivation, the N behind each, and the scenarios that remain
undetectable. Nothing enters `calibration.py` before this is scored.

---

# Result — measured 2026-08-24

Ten baseline runs at 630x for 480s, 25-step ladder, isolation asserted per run,
none degraded. First run after the node-disk fix, so `disk_ratio` appears here
as a real series for the first time. Raw data in `data/min-peers.json`.

**Three hits and two misses. The decision is that `MIN_PEERS = 12` goes.**

## The thresholds

| group | n | pooled T at 1e-3 | worst run's T | pooled covers worst? | T at 1e-4 |
|---|---|---|---|---|---|
| `memory` | 12 | 4 | 4 | **yes** | 4 |
| `cpu` | 12 | 4 | 5 | no | 5 |
| `latency` | 12 | 7 | 14 | no | 14 |
| `disk_ratio` | 3 | 9 | 12 | no | 12 |
| `ci_ratio` | 5 | 40 | 150 | no | 150 |
| `error_ratio` | 5 | 50 | 100 | no | 100 |

## P3 — HIT, and by more than predicted

The prediction was that pooling would hide a bad run for at least one service
group **and** at least one 12-peer group. It hides one for **five of six
groups**, including two of the three 12-peer groups. Only `memory` — whose
per-run T is 4 in all ten runs — is covered by its pooled value.

**A pooled bound at 1e-3 is not safe for anything except `memory`.** That is the
central result, and it is about pooling, not about peers.

## P4 — HIT

| group | T at 1e-4 | fault z (06) | margin | clears its worst run |
|---|---|---|---|---|
| `error_ratio` | 100 | 3331.63 | **33.32x** | yes |
| `ci_ratio` | 150 | 950.86 | **6.34x** | yes |
| `memory` | 4 | 30.35 | 7.59x | yes |
| `latency` | 14 | 14.21 | **1.02x** | yes |

Both service groups reach 1e-4 at a T under 200, both clear their worst
individual run, and both keep more than the predicted 4x margin to the fault.

**So the tighter target is the answer.** The 1e-3 threshold is unsafe for five
of six groups; the 1e-4 threshold clears the worst observed run for every group
that has one. That is not a coincidence - a rate ten times stricter buys roughly
the headroom the per-run spread needs.

## P2 — HIT, marginally

Pooled T by number of runs:

| group | N=2 | N=4 | N=6 | N=8 | N=10 |
|---|---|---|---|---|---|
| `memory` | 4 | 4 | 4 | 4 | 4 |
| `cpu` | 4 | 4 | 4 | 4 | 4 |
| `latency` | 7 | 7 | 7 | 7 | 7 |
| `disk_ratio` | 12 | 9 | 9 | 9 | 9 |
| `ci_ratio` | 150 | 40 | 40 | 40 | 40 |
| `error_ratio` | 70 | 50 | **60** | **60** | 50 |

Five of six settle by N = 4. `error_ratio` oscillates 70 / 50 / 60 / 60 / 50 -
one ladder step either way, which satisfies the letter of the prediction and
should be read as "stable to within a step", not "converged".

**N = 4 is the number of runs a pooled threshold needs.** N = 2 is not enough:
it puts `ci_ratio` at 150 against a settled 40, and `disk_ratio` at 12 against 9.

## P1 — FALSIFIED

`error_ratio` pooled T is **50**, inside the predicted 40 – 70. `ci_ratio` is
**40**, below its predicted 60 – 100. The falsifier named either band and fired.

Part of the gap is the ladder I fixed. 10's ladder ran `... 20, 30, 50, 80` with
no 40, so `ci_ratio` could not report 40 there and reported 80. Predicting a band
from numbers a coarser instrument produced carried its coarseness into the
prediction.

## P5 — FALSIFIED

Rank correlation against pooled T: `min(scale)/median(scale)` **-0.657**, peer
count **-0.600**. The prediction required at least 0.80 in magnitude.

The scale statistic still beats peer count, but only just, and both are weak
here. It predicted **blow-ups** at -0.932 and -0.923 in 08 and 09; it does not
predict **where a threshold has to sit**. Those are different questions and I
had assumed one statistic would answer both.

---

## The decision, against the criteria committed before the run

The pre-registered condition for replacing the count was P2 (a threshold can be
stated), P4 (it clears the worst run and still separates the fault), and P3's
second half (the failure mode is not about count). **All three hold.**

> **`MIN_PEERS = 12` is replaced.** A peer group qualifies when a threshold
> exists that clears its worst observed run at the target false-positive rate
> and still leaves margin to the faults it must catch, measured over **at least
> four runs**.

Three separate pieces of evidence say the count was never the variable:

1. A three-member group, `disk_ratio`, produces per-run T values of 8 or 9 in
   nine runs of ten and a well-behaved threshold at 12. Three peers works.
2. Two of the three twelve-member groups fail the pooled-covers-worst test that
   `ci_ratio` at five members also fails - the failure does not sort by size.
3. Peer count correlates with the needed threshold at -0.600, which is weaker
   than the scale statistic and far too weak to be a rule.

The count was standing in for "enough runs to see the worst case", and the
number of runs is the thing to state.

## Which scenarios remain undetectable

At the 1e-4 thresholds, using 06's peer fault figures:

| scenario | metric | T | fault z | margin | verdict |
|---|---|---|---|---|---|
| `bad_deploy_5xx` | error_ratio | 100 | 3331.63 | 33.32x | **detectable** |
| `memory_leak` | memory | 4 | 30.35 | 7.59x | **detectable** |
| `flaky_test_storm` | ci_ratio | 150 | 950.86 | 6.34x | **detectable** |
| `noisy_neighbor` | latency | 14 | 14.21 | **1.02x** | **not detectable** |
| `disk_pressure` | disk_ratio | 12 | **unmeasured** | - | **unknown** |

**`noisy_neighbor` is out.** Its fault reaches 14.21 and its threshold sits at
14 - a margin of 1.5%, which is not detection, it is a coin flip. Prediction 10
called this before the numbers were known, at 1.42x against the looser
threshold; the stricter one removes what was left. Peer comparison cannot see a
noisy neighbour, because the fault is partly common-mode across the node and
drags the peer median with it.

**`disk_pressure` is unknown, and that is a gap created by fixing it.** 06's
peer fault figure for `disk_ratio` was measured against the deterministic gauge
and is void. Every other 06 figure survives - the weekly refactor left all
non-disk metrics at exactly 0.72, and `_node_disk` touched nothing else - but
disk needs a fresh scenario run before it can enter the matrix with a number.
