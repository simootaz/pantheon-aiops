# Predictions 3 — written BEFORE the measurement, 2026-08-20

Targets read as data first, not from descriptions:

    noisy_neighbor
      batch_starts          target=search   cpu       -> 2/12 pods (search 2/2)
      neighbours_throttled  target=node-c   latency   -> 4/12 pods
                            catalog 1/3, notifier 1/2, search 2/2

Cluster: catalog 3, checkout 3, notifier 2, payments 2, search 2. Nodes 4 each.

## P1 — the 22.76 latency baseline is a transient, not a level

Reproduced exactly across two runs, same metric, same 12 peers, 4x every other
scenario. Predicted: it is a small number of spikes, not a raised floor.

- Fraction of baseline timestamps with peer z > 10: **under 5%**
- 95th percentile of baseline peer z: **below 8**

FALSIFIED IF over 20% of baseline timestamps exceed 10 - that would be a
persistently noisy baseline and a different problem.

Mechanism guess, stated separately so it can fail on its own: per-pod seasonal
phase shift (`_seed(pod.name, metric)` gives each pod up to 0.04 of a cycle of
offset). At 360x one cycle is 240s wall, so 0.04 is ~9.6s - during the steepest
part of the curve, pods offset by 9.6s differ materially. If so the high-z
timestamps CLUSTER at the curve's steep sections rather than spreading evenly.

FALSIFIED IF high-z timestamps are uniformly distributed through the baseline.

## P2 — minimum usable peer-group size

Subsample the 12 pods into groups of 3, 4, 5, 6, 8, 12 on clean baseline
latency. Predicted baseline max |z| by group size:

| peers | predicted baseline max |
|---|---|
| 3 | > 50, or exactly 0 (degenerate - MAD is 0 whenever two of three agree) |
| 4 | 15 - 50 |
| 5 | 8 - 25 |
| 6 | 6 - 15 |
| 8 | 4 - 10 |
| 12 | 3 - 8 |

**Predicted minimum usable size (baseline max < 8): 8 peers.**

FALSIFIED IF 5 or 6 peers produce a baseline max below 8 - that would make
service-mate grouping viable and hierarchical selection available.

## P3 — service-mate grouping does NOT rescue noisy_neighbor

Because the target set says so, not because the method fails:

| group | size | affected | predicted |
|---|---|---|---|
| search | 2 | 2/2 | peer z < 3 during fault - pure common-mode, invisible |
| catalog | 3 | 1/3 | fault z high but 3-peer baseline degenerate; separation < 3x |
| notifier | 2 | 1/2 | 2-member MAD; unusable either way |

**Predicted: service-mate separation for `noisy_neighbor` is WORSE than
all-12.** Node-mate is worse still - node-c is 4/4 affected, fully common-mode.

FALSIFIED IF any service-mate grouping gives separation above 3x.

## P4 — the refusal

Peer-relative must refuse below the measured minimum rather than return a
number. `disk_ratio` at 3 peers produced 1599.63 on CLEAN data in one scenario
and 1585.74 as a "signal" in another - the same degeneracy with opposite
labels, and in production the first is a silent false positive.

Predicted minimum to encode: **8 peers**. If P2 falsifies at 5 or 6, that
number changes and hierarchical grouping becomes available.

---

# Result — measured 2026-08-21

## P1 — FALSIFIED, and the anomaly moved

```
baseline n=483   max=5.04   p95=3.45   frac>10=0.0%   median=2.24
high-z moments: []
```

Not a transient and not a raised floor - **the 22.76 was absent entirely** on a
standalone run. At the time this was attributed to partial peer coverage; that
explanation was itself wrong (coverage measured 100%, 1501 timestamps, zero
gaps). The cause was a reset that never cleared - see
[05](05-run-ordering.md).

## P2 — direction confirmed, numbers falsified

The sweep here used the *first* 40 subsets lexicographically, which
over-represents the earliest pods and makes per-size figures incomparable. A
seeded random sweep (seed 20260821, `data/peer-group-size-sweep.json`) replaced
it:

| peers | median | p90 | worst | frac > 8 |
|---|---|---|---|---|
| 3 | 365.01 | 1388.77 | 9444.81 | 100% |
| 4 | 10.97 | 74.19 | 719.88 | 70% |
| 5 | 15.27 | 72.62 | 359.87 | 78% |
| 6 | 8.25 | 43.04 | 216.40 | 52% |
| 8 | 6.57 | 12.17 | 30.70 | 42% |
| 10 | 5.72 | 7.69 | 11.97 | 8% |
| 12 | 5.35 | 5.35 | 5.35 | 0% |

Predicted minimum was 8; at 8 peers the median is 9.11 and 42% of subsets exceed
8, so **the prediction is wrong and the minimum is 12**.

**The tail decides, not the median.** Three peers has a *best* subset of 24.92 -
a particular small group can look well behaved while every neighbouring choice
is catastrophic, so sampling one group proves nothing about the size.

## P3 — CONFIRMED

| axis | group | peers | baseline | fault | separation |
|---|---|---|---|---|---|
| all-12 | all | 12 | 5.04 | 23.80 | **4.72x** |
| service-mates | checkout | 3 | 220.19 | 276.11 | 1.25x |
| service-mates | catalog | 3 | 454.03 | 206.75 | 0.46x |
| node-mates | node-b | 4 | 7.38 | 6.60 | 0.89x |
| node-mates | node-c | 4 | 10.51 | 2.33 | 0.22x |
| either | notifier, payments, search | 2 | - | - | refused |

Service-mate and node-mate grouping are both worse, as predicted from the target
set: `search` is 2 pods both on node-c, so 2/2 are affected and the comparison
is pure common-mode within the service.
