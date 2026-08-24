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

# Result — measured 2026-08-24

One `disk_pressure` run at 630x: 617s wall, 275 baseline instants, 342 fault
instants, not degraded. Peak ratio 0.8932, matching the offline projection of
0.8925. Raw data in `data/disk-fault.json`.

| quantity | measured |
|---|---|
| baseline max abs z | **6.04** |
| fault max abs z | **1580.53** |
| baseline floor fraction | 48.7% |
| fault floor fraction | **19.0%** |
| margin over the 1e-4 threshold of 12 | **131.7x** |

## P2 — HIT

`disk_pressure` is detectable, by 131.7x against a required 6x.

## P1 — FALSIFIED, and the reason is embarrassing in a useful way

Predicted 80 – 400. Measured **1580.53**, four times the top of the band. The
floor clause held at 19.0% against a bound of 20%, close enough that it decided
nothing.

The arithmetic was stated in advance so it could be checked, and checking it
finds the error exactly. I estimated the scale from the **measured baseline
range over time**, 0.3355 – 0.3451, and took the spread of two unaffected nodes
to be of that order - about 0.003. The measured scale implies roughly 3.5e-4,
ten times smaller.

That temporal range is dominated by the **seasonal swing**, which is 1% of
level. But the three nodes are compared **at a single instant**, where they all
sit at the same point of the same daily curve. Seasonality is common-mode across
peers, so it cancels, and the scale is set by noise alone - which is 0.004
relative, halved again by averaging four pods per node.

> **Peer comparison removes exactly the component I used to estimate its
> scale.** Cancelling common-mode seasonality with no window and no period
> estimate is the property that makes the peer path worth having, and it is the
> first thing established on this branch. I forgot it while predicting the
> behaviour of the method it defines.

The consequence is not confined to this prediction. Any estimate of a peer
scale taken from a series' variation **over time** will be too large by the
ratio of seasonal amplitude to noise - here about 10x, and for `cpu`, whose
seasonal amplitude is 0.45 against noise of 0.06, closer to 50x.

## The floor, which is a real caveat

The scale floor engages on **48.7% of baseline instants**. For nearly half the
baseline, the three-node group's MAD collapses below `min|v| * 1e-3` and the
comparison is measuring the floor rather than the data.

This is conservative in direction - the floor is a lower bound on the scale, so
engaging it makes z *smaller* - and it does not threaten the verdict here,
because the fault clears its threshold by 131.7x with the floor active for 19%
of the fault window.

It does mean `disk_ratio`'s **baseline** numbers are half floor-determined, and
that any future work tightening the disk threshold has to fix the floor first.
Three nodes is where the scale estimator was always going to be worst, and 11
already established that group size does not decide safety - this is the same
finding from the other end: a three-member group is usable and its scale is
still half artificial.
