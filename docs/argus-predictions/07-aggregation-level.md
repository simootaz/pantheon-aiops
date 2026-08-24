# Predictions 7 — is the peer/temporal split per aggregation level?

Written BEFORE the measurement, 2026-08-24, on `feature/argus-aggregation-levels`.

## The hypothesis under test

Not mine. Proposed as a hypothesis and explicitly not as a conclusion, which is
the right handling given that the last three mechanisms of this shape were
wrong.

> The split may not be per-metric at all. It may be per **aggregation level**:
> pod-level metrics (memory, latency, cpu — 12 peers) go peer-relative, needing
> no period estimate; service- and node-level metrics (error_ratio, ci_ratio,
> disk_ratio — 5 and 3 peers) go temporal at W = one diurnal cycle. Small groups
> are not small by accident: a cluster has few services and few nodes by the
> shape of the system, and no amount of scaling fixes that.

It makes a testable claim: **service- and node-level metrics should be quiet
under the temporal path.** `error_ratio` already gave 5.68 / 7.28 / 4.53 at
whole-cycle windows against 25–52 under peer comparison. If `ci_ratio` and
`disk_ratio` behave the same way, the split is principled.

## What the measurement is

Robust z (median + 1.4826·MAD) computed **temporally** — each series against its
own trailing history at W = one diurnal cycle — on the same five scenarios as
[06](06-experiment-b-rerun.md), under the same asserted isolation (`carried=0`
on every pair, or the run is discarded). Baseline excursion is the maximum |z|
over fault-free windows; fault z uses the window ending at fault onset, so the
fault never enters its own baseline. Scored by **separation**, not by fault
magnitude.

---

## P2 first: one of the three cells cannot answer the question

Read before running, not after. `_node_disk()` in `simulator/metrics_generator.py`
does not go through `_baseline()`. It returns

```python
used = 0.34 * node.disk_bytes
used += 0.00004 * node.disk_bytes * (simulated_seconds / SECONDS_PER_DAY)
```

and nothing else. **No noise term and no seasonal term** — `SEASONAL_AMPLITUDE`
and `NOISE` are applied in `_baseline`, which the node disk gauge never calls.
The exported `disk_ratio` is a deterministic straight line at 0.34 with a drift
of 4e-5 per simulated day.

So the prediction for `disk_ratio` is neither "quiet" nor "noisy":

> **P2 — degenerate under temporal, for the same reason it was degenerate under
> peer.** MAD over any baseline window is at or near zero, the scale floor
> engages on **at least 95%** of baseline windows, and baseline |z| reads about
> zero — which will *look* like the cleanest result in the table and will mean
> nothing. The 0.00 peer baseline in 06 was the same artifact seen from the
> other side.

**Falsified if** the floor engages on under 50% of baseline windows, or baseline
MAD exceeds 1e-6 in ratio units — either would mean I have misread the
generator.

This is the third time the ground truth has had a property the real system does
not. It does not invalidate the hypothesis; it means the hypothesis is being
tested on two metrics, not three, and that a fix to the simulator is owed before
`disk_ratio` gets a threshold.

---

## P1 — `ci_ratio` is quiet under temporal

`ci_ratio` does go through `_baseline`: seasonal amplitude 0.30, and it is the
mean of a service's 2–3 pods, so its noise is reduced by averaging.

> Maximum baseline |z| over fault-free whole-cycle windows lands in **2.5 – 7**,
> the band `error_ratio` occupies (4.53 – 7.28), and well under the 19.04 it
> shows under peer comparison in 06.

**Falsified if** it exceeds 10.

Prior evidence, and the reason this is the weakest prediction here: 01 already
measured `ci_ratio` at 3.38 (1 cycle) and 3.05 (2 cycles). That run predates the
reset fix. If those numbers reproduce, the prediction is confirmed but has
demonstrated little.

---

## P3 — the control the hypothesis needs, and does not state

A split needs both halves justified. "Temporal suits service-level metrics" is
only an argument for a split if temporal is **worse** for pod-level metrics.
If temporal is quiet for everything, the simpler reading is that temporal always
works and its cost is a period estimate.

> Pod-level metrics are **also quiet** under temporal at whole-cycle windows:
> maximum baseline |z| in **2 – 6** for memory, latency and cpu.

Prior: 01 gives latency 3.31 / 2.72 and cpu 2.15 / 2.01 at whole-cycle windows.

**If P3 holds, the hypothesis as stated is wrong, and a narrower version of it
survives:** aggregation level does not determine which comparison *suits* a
metric. It determines whether peer comparison is **available at all**, because
peer needs 12 peers and only pod-level has them. That distinction matters,
because it predicts that a 30-node cluster should use peer comparison for
node-level metrics, whereas the hypothesis as written says node-level is
temporal by nature.

**The hypothesis as stated survives only if** pod-level temporal exceeds 10
while service-level stays under 7.

---

## P4 — separation, which is what actually decides this

Quiet is half a result. A metric with a silent baseline and a silent fault
detects nothing. Predicted temporal separation, beside the peer numbers from 06:

| scenario | metric | peer sep (06) | predicted temporal sep |
|---|---|---|---|
| `bad_deploy_5xx` | error_ratio | 64.3x | **at least 20x** |
| `flaky_test_storm` | ci_ratio | 50.0x | **at least 15x** |
| `noisy_neighbor` | latency | 2.4x | **at least 5x — better than peer** |
| `memory_leak` | memory | 7.7x | **3 – 10x — comparable or worse** |
| `disk_pressure` | disk_ratio | degenerate | degenerate, uninformative |

The two directional calls, with their reasons, so a hit is worth something:

- **`noisy_neighbor` improves.** Peer comparison is weak there (2.4x) because
  the fault hits several pods on one node at once, so the contamination is
  partly common-mode and the median moves with it. Temporal comparison has no
  such coupling.
- **`memory_leak` does not improve, and may degrade.** It is a slow ramp. A
  trailing window absorbs a ramp — that is the sustained-fault-longer-than-W
  limitation, and a memory leak is the scenario built to trigger it.

**Falsified if** `noisy_neighbor` comes back below 2.4x, or `memory_leak` above
10x.

---

## P5 — the confound, and a test that separates it

Aggregation level and group size are **perfectly confounded** in this
simulator: every service-level metric has 5 peers and every node-level one has
3, against 12 for every pod-level metric. No result from the table above can
tell the two apart.

They are separable, because group size cannot enter the temporal path at all —
each series is compared against its own history, and no other series is read.

> **P6 — temporal z for a single pod's memory is unchanged, to within floating
> point, whether the analysis is given 3 peer series or 12.** Predicted
> identical to at least 6 significant figures for the same pod on the same data.

If P6 holds, group size is provably absent from the temporal path, so any
level-dependence that shows up in P1/P3 must come from metric character rather
than from how many peers exist. If P6 fails, the temporal implementation is
reading something it should not, and that is a defect to fix before any of the
rest of this is scoreable.

---

## Stated before the run: what each outcome licenses

| outcome | what it licenses |
|---|---|
| P1 holds, P3 holds | Split is by **peer availability**, not metric character. Peer where 12 peers exist, temporal elsewhere. Hypothesis right in practice, wrong in mechanism. |
| P1 holds, P3 fails | Hypothesis right as stated. Aggregation level really does select the method. |
| P1 fails | Some metrics are hard under both paths, and `ci_ratio` is one. No split rescues it; it needs a different signal or no threshold at all. |
| P4 misses on both directional calls | The separation model is not understood well enough to set thresholds, and the matrix waits. |

**No threshold or scale floor is written on the basis of this run until it is
scored.** The matrix that follows is scoped by whichever row above turns out to
be the true one.

---

# Result — PENDING

The measurement has not been run. These predictions were committed first, on
purpose, and this section is a placeholder so that "not yet scored" is a state
the repository states rather than a gap it happens to have.

