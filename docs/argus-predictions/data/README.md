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

Each row carries `window_start` and `fault_from` where applicable, so a window
can be reconstructed rather than inferred. Not storing those cost two re-runs
earlier in this work.
