# Predictions 10 — is the peer bound uncalibratable, or just under-sampled?

Written BEFORE the measurement, 2026-08-24, on `feature/argus-peer-bound`.

## The distinction being tested

"Peer comparison is not calibratable for any group" was stated at the end of 09
and conflates two claims with different remedies:

1. **Uncalibratable in principle on this data.** No bound exists.
2. **One run is not enough to bound it.** The remedy is N runs and a bound over
   their distribution — which is exactly how the temporal false-positive bound
   was measured.

`error_ratio` at 51.82 / 25.73 / 38.65 and `latency:raw` at 5.56 → 8.42 both
look like the second.

## A third possibility, which is what these predictions expect

Not a third reading of the evidence — a claim about the statistic rather than
the sample.

Every peer number in 08 and 09 is a **maximum over a run**. A maximum is an
extreme-value statistic: it is non-decreasing in the number of instants
observed, so pooling runs makes it grow rather than converge. If that is what is
happening, then **no number of runs stabilises it**, and (1) would be true of
`max abs z` while being false of the metric that matters.

The temporal false-positive bound did not have this problem, because it was
measured as a **rate** — excursions per unit time above a threshold. A rate is
an average, it converges, and pooling runs shrinks its error.

So the failure in 09 may be neither "no bound exists" nor "too few runs", but
"the wrong summary was bounded". That is a fourth sample-size-or-statistic
artifact for this branch if it holds, and it is being predicted rather than
assumed.

## The measurement

Six fresh baseline-only runs at 630x for 480s, timestamps recorded, isolation
asserted per run. For every group, per run: `max abs z`, the number of instants,
and the **exceedance count above a ladder of thresholds** (4, 5, 6, 8, 10, 12,
15, 20, 30, 50) so a rate can be computed at each.

08 and 09 were both 480s baseline runs at 630x, so their maxima join the
max-curve as two additional points. Their rates were not recorded and do not.

Groups: the three raw 12-pod groups, the two raw 5-service groups, and seeded
8-pod subsets — the sizes that matter for the eventual matrix.

---

## P1 — the maximum does not stabilise

> The running maximum over k runs keeps rising. For the three raw 12-pod groups,
> `max over 8 runs` is at least **1.4x** the median single-run maximum, and for
> at least two of the three groups the **final run still raises it**.

**Falsified if** the running maximum is within 1.4x of the median single-run
maximum, or if the last two runs raise it for at most one group. Those are the
same event stated from both sides: a plateau.

## P2 — the rate does stabilise

> At T = 6, the exceedance rate for the raw 12-pod groups has a run-to-run
> relative standard deviation **below 0.50**, and the pooled estimate after k
> runs changes by **under 20%** between k = 4 and k = 6.

**Falsified if** the relative standard deviation is 0.50 or above, or the pooled
estimate moves by 20% or more between k = 4 and k = 6.

## P3 — how many runs

> The pooled rate is within **25%** of its six-run value by **N = 4**, and not by
> N = 2.

**Falsified if** it is within 25% at N = 2 (fewer runs needed than claimed), or
still outside 25% at N = 4 (more needed).

## P4 — a threshold exists for the 12-pod groups

> There is a T in **8 – 14** at which every raw 12-pod group has a pooled
> exceedance rate at or below **1e-3**, and the per-run T meeting that rate
> varies by no more than **±2** across the six runs.

**Falsified if** no T at or below 14 reaches 1e-3 for all three, or if the
per-run T spans more than 4.

This is the claim that decides whether the earlier conclusion was an artifact.
If it holds, peer comparison **is** calibratable for pod-level metrics and 09's
closing sentence was wrong.

## P5 — the service groups stay uncalibratable at usable thresholds

> For `error_ratio` and `ci_ratio` at 5 members, the smallest T reaching a
> pooled rate of 1e-3 is **above 60**.

A threshold above 60 is not usable: `noisy_neighbor`'s peer fault z was 14.21
and `memory_leak`'s 30.35, so a detector armed at 60 would miss faults that
peer comparison is otherwise able to see.

**Falsified if** either group reaches 1e-3 at a T of 60 or below — which would
mean the small groups are calibratable too, and `MIN_PEERS` is wrong in the
other direction from the one 09 left it in.

## P6 — the practical consequence, stated as a number before it is known

> At the T that P4 selects, the four non-degenerate scenarios from 06 separate
> as follows: `memory_leak` (peer fault z 30.35) and `bad_deploy_5xx` (3331.63)
> and `flaky_test_storm` (950.86) clear it; **`noisy_neighbor` (14.21) does
> not** clear T + a factor of 1.5.

**Falsified if** `noisy_neighbor` clears 1.5 x T, or if any of the other three
fails to.

---

## What each outcome licenses

| outcome | what it licenses |
|---|---|
| P1 and P2 and P4 hold | The bound is calibratable and 09's conclusion was a statistic artifact, not a data limit. The matrix gets rate-based thresholds with stated false-positive rates and a stated N. |
| P1 holds, P2 fails | Neither summary converges. That is claim (1) — uncalibratable on this data — and it is now evidenced rather than inferred from one run. |
| P1 fails | The maximum plateaus, so a max-based bound over N runs is legitimate and simpler. Use it. |
| P4 fails, P2 holds | Rates converge but no usable threshold exists for peer comparison at any group size. Peer-relative is dropped from the matrix with a measured reason. |
| P5 falsified | `MIN_PEERS` is wrong in the opposite direction: the small groups qualify and the 12-peer rule is excluding usable signal. |

No threshold enters `calibration.py` from this run either. The matrix follows
the scoring.

---

# Result — measured 2026-08-24

Six baseline runs at 630x for 480s, isolation asserted per run, none degraded.
08 and 09 were the same shape and join the max-curve, giving eight points there.
Raw data in `data/peer-bound.json`.

**Two hits and four misses, and the hit is the one that decides the question.**

## The third possibility was wrong

These predictions expected the failure to be about the *statistic* - that a
maximum cannot converge because it is non-decreasing in the number of instants
observed. P1 tested that directly and it is false.

| group | n | min | max | median | max / median |
|---|---|---|---|---|---|
| `memory` | 12 | 3.91 | 4.03 | 3.96 | **1.02** |
| `cpu` | 12 | 2.98 | 4.18 | 3.28 | 1.28 |
| `latency` | 12 | 5.47 | 9.76 | 7.96 | 1.23 |
| `error_ratio` | 5 | 20.95 | 63.03 | 30.36 | 2.08 |
| `ci_ratio` | 5 | 32.34 | 77.45 | 58.99 | 1.31 |

Eight runs each. `memory`'s peer maximum lands between 3.91 and 4.03 every
single time - a spread of 3%. The maximum plateaus because a peer z is bounded
by the *structural* spread of the group, which is a property of the topology
rather than a tail draw. That is the same finding 08 and 09 arrived at from the
other direction: heterogeneity bounds z.

**So the answer is the second of the two readings, not a third one.** One run
was not enough. It is the fourth sample-size artifact this branch has produced.

---

## P1 — FALSIFIED

Predicted the running maximum would reach at least 1.4x the median single-run
maximum for the raw 12-pod groups. Measured **1.02, 1.28, 1.23**. The falsifier
was written at the edge and fired.

Per the outcome table committed before the run: *"the maximum plateaus, so a
max-based bound over N runs is legitimate and simpler."*

## P2 — FALSIFIED, and the evaluation point was badly chosen

Predicted the T = 6 exceedance rate would have a run-to-run relative standard
deviation below 0.50. `latency` came back at **0.610**.

Worse, `memory` and `cpu` never exceed 6 in any of the six runs, so their rate is
exactly zero and the relative standard deviation is undefined. **T = 6 sits
outside the informative range for two of the three groups I chose it to
measure** - a design fault in the prediction, not a property of the data. The
statistic was fine; the point at which I sampled it was not.

## P3 — FALSIFIED on both sides at once

Predicted convergence within 25% by N = 4 and not by N = 2.

| group | k=2 vs k=6 | k=4 vs k=6 |
|---|---|---|
| `ci_ratio` | 0.03 | 0.04 |
| `error_ratio` | 0.08 | 0.04 |
| `latency` | 0.17 | 0.03 |
| `latency:8` | 0.75 | 0.07 |
| `cpu:8` | 1.00 | **1.00** |

The three full groups are already inside 25% at N = 2, and `cpu:8` is still
outside it at N = 4 and at N = 6. Both halves of the falsifier fired.

**N is a property of the group, not of the method.** Full 12-member groups
converge in two runs; 8-member subsets had not converged in six, because runs 5
and 6 produced exceedances that runs 1 to 4 had none of.

## P4 — HIT, and it settles the question

Smallest T reaching a pooled exceedance rate of 1e-3:

| group | pooled T | per-run T | spread |
|---|---|---|---|
| `memory` | **4.0** | 4, 4, 4, 4, 4, 4 | **0.0** |
| `cpu` | **4.0** | 4, 4, 4, 4, 4, 5 | 1.0 |
| `latency` | **10.0** | 8, 10, 6, 10, 10, 8 | 4.0 |

T = **10** holds all three raw 12-pod groups at or below 1e-3, inside the
predicted 8 – 14, and every per-run spread is within the predicted 4.

**Peer comparison is calibratable for pod-level metrics.** 09's closing sentence
- "peer comparison is not yet calibratable for any group" - is wrong, and was
wrong because it generalised from a single run's maximum against a cutoff I had
declared rather than derived.

## P5 — FALSIFIED

Predicted both service groups would need T above 60. `ci_ratio` needs **80.0**;
`error_ratio` needs **50.0**, which is below the bound, so the falsifier fired.

The number that matters more is not the pooled one. `error_ratio`'s per-run T is
**30, 30, 30, 80, 50, 50** - a spread of 50. A threshold derived from any single
run would be wrong by up to a factor of 2.7 for the next one. The pooled value
is stable; the per-run value is not, which is exactly the distinction P4
establishes for pod metrics and which the service groups fail.

## P6 — HIT

Predicted, before the thresholds were known, which scenario the resulting
threshold would fail to clear comfortably. Against 06's peer fault figures:

| scenario | metric | fault z | its T | margin |
|---|---|---|---|---|
| `bad_deploy_5xx` | error_ratio | 3331.63 | 50 | 66.6x |
| `flaky_test_storm` | ci_ratio | 950.86 | 80 | 11.9x |
| `memory_leak` | memory | 30.35 | 4 | 7.6x |
| `noisy_neighbor` | latency | 14.21 | 10 | **1.42x** |

`noisy_neighbor` clears its threshold and does not clear 1.5x it, as predicted.
It is the scenario with no margin.

---

## What this changes

**06's "peer-relative detects 2 of 5" was a sample-size artifact.** With
thresholds derived over six runs rather than one, all four non-degenerate
scenarios clear their metric's threshold. `disk_pressure` remains degenerate for
the reason 07 established, which is a simulator defect and not a detection
result.

**The pod-level path is ready to calibrate.** `memory` at T = 4 with a per-run
spread of zero across six runs is the most stable number this branch has
produced.

**The service-level path is not, and the reason is now specific.** Not "too few
peers" and not "no bound exists" - the pooled bound exists and is 50 and 80. The
problem is that a *single run* estimates it anywhere between 30 and 80, so
nothing derived from one run is trustworthy, and the matrix has to say how many
runs a threshold requires before it can be written.

**And it re-opens `MIN_PEERS` in the direction 09 did not expect.** At their
pooled thresholds both service groups separate their faults by 12x and 67x. The
12-peer rule refuses them. That is now a decision for the matrix with numbers
behind it rather than a rule inherited from a sweep - and it needs its own
prediction before anything is changed, because this is one experiment and the
per-run spread is the reason for the rule in the first place.
