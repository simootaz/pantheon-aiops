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

# Result — PENDING

The measurement has not been run. Predictions committed first; this section is
a placeholder so that "not yet scored" is a state the repository states.
