# Predictions 12 — the one number the disk fix voided

Written BEFORE the measurement, 2026-08-24, on `feature/argus-min-peers`.

## Why this is needed

11 could state a verdict for four of five scenarios. `disk_pressure` came back
**unknown**, because fixing the generator voided its number: 06 measured
`disk_ratio`'s peer fault z against a gauge that carried no noise and no
seasonality, where the scale was always the floor. Every other 06 figure
survives - the weekly refactor left non-disk metrics at exactly 0.72 and
`_node_disk` touched nothing else - but this one has to be re-measured before
the threshold matrix can say whether `disk_pressure` is detectable.

One `disk_pressure` run at 630x, isolation asserted, peer z across the three
nodes, fault window taken from the runner rather than inferred.

## The reasoning, so the prediction is not a guess

Baseline is 0.34 on every node. The fault ramps **node-a only**, to 0.8925.
So at the peak the three values are roughly `[0.89, 0.34, 0.34]`: the median is
0.34, and the MAD is driven by the two *unaffected* nodes, whose spread is now
noise plus seasonality rather than zero.

Deviation of the affected node is about 0.55. The scale is roughly 1.4826 times
the median absolute deviation of two near-identical values, which the measured
baseline spread of 0.3355 – 0.3451 puts at the order of 0.003.

> **P1 — `disk_ratio` peer fault z lands in 80 – 400**, and the scale floor
> engages on **under 20%** of fault windows.

**Falsified if** it falls outside 80 – 400, or the floor engages on 20% or more
of fault windows - the latter meaning the metric is still floor-dominated and
the fix did not reach the case that matters.

> **P2 — `disk_pressure` is detectable**: the fault z clears the 1e-4 threshold
> of 12 by at least **6x**.

**Falsified if** the margin is under 6x.

## What each outcome licenses

| outcome | what it licenses |
|---|---|
| both hold | `disk_pressure` enters the matrix as detectable, and four of five scenarios are covered. |
| P1 holds, P2 fails | Detectable but with thin margin - it joins `noisy_neighbor` as a scenario peer comparison cannot be trusted on. |
| floor still engages | The node-disk fix did not reach the fault path, only the baseline. That is a defect to fix before the matrix, not a result to record. |

---

# Result — PENDING

The measurement has not been run. Predictions committed first; this section is
a placeholder so that "not yet scored" is a state the repository states.
