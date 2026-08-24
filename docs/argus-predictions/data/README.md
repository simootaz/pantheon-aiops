# Raw measurements behind the scorings

The numbers each scoring cites, as produced. Committed because they lived only
in a session scratchpad - a temp directory that is cleaned up - and they are the
only defensible peer-relative measurements taken so far.

| file | produced by | cited in |
|---|---|---|
| `experiment-b-rerun.json` | five scenarios, isolation asserted, `carried=0` throughout | [06](../06-experiment-b-rerun.md) |
| `run-ordering.json` | three conditions S / A / N, N reproducing 22.76 | [05](../05-run-ordering.md) |
| `peer-group-size-sweep.json` | seeded random subsets, seed 20260821 | [03](../03-grouping-and-group-size.md) |
| `aggregation-level.json` | temporal path at W = one diurnal cycle, 36 metric-run pairs, `carried=0` throughout | [07](../07-aggregation-level.md) |
| `scale-stability.json` | one baseline run, 2x2 of size against normalisation, seed 20260824 | [08](../08-peer-scale-stability.md) |
| `scale-quantiles.json` | 154 groups re-queried from the same recorded window | [08](../08-peer-scale-stability.md) |
| `threshold-validation.json` | fresh run, seed 20260825, out-of-sample test of the fitted threshold | [09](../09-threshold-validation.md) |
| `peer-bound.json` | six baseline runs, per-run maxima and exceedance counts at a threshold ladder | [10](../10-peer-bound-over-runs.md) |
| `min-peers.json` | ten baseline runs, 25-step ladder, both 1e-3 and 1e-4 targets, post node-disk fix | [11](../11-min-peers-decision.md) |
| `disk-fault.json` | one disk_pressure run after the node-disk fix, peer z with floor engagement reported separately | [12](../12-disk-fault-remeasure.md) |
| `threshold-matrix.json` | floors from runs 1-5, thresholds from runs 6-10, held out | [argus-threshold-matrix.md](../../argus-threshold-matrix.md) |
| `scenario-faults.json` | all five scenarios re-measured under the p05 floors, `carried=0` throughout | [argus-threshold-matrix.md](../../argus-threshold-matrix.md) |

Each row carries `window_start` and `fault_from` where applicable, so a window
can be reconstructed rather than inferred. Not storing those cost two re-runs
earlier in this work.
