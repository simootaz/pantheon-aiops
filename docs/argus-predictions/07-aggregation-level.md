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

# Result — measured 2026-08-24

One speed throughout (630x, W = 137 samples). Isolation asserted on every run:
`carried = 0` on **all 36** metric-run pairs, so no series repeated a previous
run's final value at its window's first sample. Raw data in
`data/aggregation-level.json`.

## Baseline excursion, temporal, W = one diurnal cycle

| metric | level | series | windows | max abs z | floor engaged | min MAD-scale |
|---|---|---|---|---|---|---|
| `memory` | pod | 12 | 4116 | **2.04** | 0.0% | 2.094e+07 |
| `cpu` | pod | 12 | 4116 | **2.08** | 0.0% | 7.055e-02 |
| `latency` | pod | 12 | 4116 | **3.31** | 0.0% | 7.289e-03 |
| `ci_ratio` | service | 5 | 1715 | **2.87** | 0.0% | 5.609e-03 |
| `error_ratio` | service | 5 | 1710 | **5.81** | 0.0% | 4.836e-04 |
| `disk_ratio` | node | 3 | 1029 | **0.06** | **100.0%** | 1.405e-05 |

Two independent reproductions: `latency` at 3.31 is identical to 01's
whole-cycle figure, and `error_ratio` at 5.81 sits inside 02's 4.53 - 7.28 band.
Different runs, four days apart, after the reset fix.

## Detection, each scenario's own metric

| scenario | metric | fault abs z | temporal sep | peer sep (06) | better |
|---|---|---|---|---|---|
| `bad_deploy_5xx` | error_ratio | 95.47 | 16.43x | 64.29x | peer, 3.9x |
| `flaky_test_storm` | ci_ratio | 58.91 | 20.53x | 49.95x | peer, 2.4x |
| `noisy_neighbor` | latency | 15.78 | 4.77x | 2.42x | **temporal, 2.0x** |
| `memory_leak` | memory | 10.95 | 5.38x | 7.70x | peer, 1.4x |
| `disk_pressure` | disk_ratio | 324.91 | 5242.18x | degenerate | neither |

Every metric not targeted by its scenario sat between 0.87x and 1.62x - 30 of
the 36 pairs are negative controls, and they behaved as such. That matters more
than usual here, because baseline and fault come from **different runs**: the
baseline excursion needed a run longer than one cycle, and no scenario provides
one before its fault. Controls at about 1.0 are the evidence that the cross-run
reference is fair.

---

## P1 - HIT

`ci_ratio` maximum baseline excursion **2.87**, predicted 2.5 - 7. Quiet under
temporal, against 19.04 under peer comparison.

## P3 - HIT

`memory` 2.04, `cpu` 2.08, `latency` 3.31 - all inside the predicted 2 - 6.
**Pod-level metrics are as quiet under temporal as service-level ones.**

## P6 - HIT

Temporal z for `catalog-9a1d3e-a1` was **bit-identical** with 3 series in scope
and with 12: maximum absolute difference exactly 0.0. Group size cannot enter a
path that reads one series.

## P2 - MISS, and the miss is the useful part

The claim held: `disk_ratio` baseline excursion **0.06**, floor engaged on
**100%** of windows against a predicted 95%.

The stated falsification condition was *"baseline MAD exceeds 1e-6 in ratio
units"*. It came back at **1.405e-05**, fourteen times over the bound, so by the
condition I wrote, P2 is falsified.

The drift did it - `0.00004 * disk_bytes` per simulated day, which over a
one-cycle window produces a MAD of order 1e-5. That line is quoted verbatim two
paragraphs above the bound it breaks. The clause was meant to operationalise "I
have misread the generator"; I had not misread it, and the clause tested
something else. A falsification condition that cannot distinguish the error it
was written to catch is a defect in the prediction, and it scores as a miss.

**What the cell does show, and it is worth the run on its own:** the floor
engaged on 100% of *fault* windows too. When the floor carries every window, the
output is not a z-score at all - it is the raw deviation divided by a constant,
and the median and MAD contributed nothing to any of 342 windows. That is how a
metric produces the largest number in the experiment, 5242x, and means nothing
by it. The 0.00 peer baseline in 06 was the same artifact seen from the other
side.

## P4 - two of four hit; both directional calls hit

| call | predicted | measured | |
|---|---|---|---|
| `error_ratio` | at least 20x | 16.43x | miss |
| `ci_ratio` | at least 15x | 20.53x | hit |
| `latency` beats peer's 2.42x | at least 5x | 4.77x | direction hit, magnitude miss |
| `memory` does not improve | 3 - 10x | 5.38x | hit |

The magnitudes were ordered wrongly: `error_ratio` was predicted to separate
better than `ci_ratio` (20x against 15x) and did the opposite (16.43x against
20.53x).

**Both directional calls hold.** `noisy_neighbor` improves on peer comparison
by 2.0x, because a fault hitting several pods of one node is partly common-mode
and drags the peer median with it. `memory_leak` degrades, because a trailing
window absorbs a ramp - its fault runs 131 samples against W = 137, so by the
last fault sample 131 of the 137 trailing samples are themselves fault.

### The prediction defect this exposes

Two of the five falsification conditions were miscalibrated against their own
point predictions, in opposite directions. P2's bound was so tight that a term
I had quoted myself broke it. P4's `latency` bound was so loose (below 2.42x)
that the 4.77x result misses the point prediction of 5x without triggering the
falsification condition at all. A point prediction and a falsification condition
that disagree about what counts as failure make the scoring a judgement call,
which is what writing them down first is supposed to prevent.

---

## What this licenses, per the table committed before the run

P1 holds and P3 holds, so: **the split is by peer availability, not by metric
character.** The hypothesis is right about what to do and wrong about why.
Nothing in the temporal path prefers a high-aggregation metric, and P6 shows it
cannot: pod-level metrics are as quiet as service-level ones, and `ci_ratio` at
2.87 is quieter than `latency` at 3.31.

The distinction is not academic. "Node-level is temporal by nature" and "peer
needs 12 peers and only pod-level has them" agree on this 3-node cluster and
disagree on a 30-node one, where the second says use peer comparison for node
metrics.

## The result that was not predicted, and re-opens a settled number

Ordering peer against temporal by group size gives the opposite of what the
hypothesis implies:

| metric | peers | peer sep | temporal sep |
|---|---|---|---|
| `error_ratio` | **5** | **64.29x** | 16.43x |
| `ci_ratio` | **5** | **49.95x** | 20.53x |
| `memory` | 12 | 7.70x | 5.38x |
| `latency` | 12 | 2.42x | **4.77x** |

Peer comparison separates **best on the small groups** - the two service-level
metrics the hypothesis assigns to temporal - and worst on a 12-peer one.

This bears directly on `MIN_PEERS = 12`, which 06 used to conclude that peer
comparison detects only 2 of 5 scenarios. That rule came from a sweep over
**random subsets of pods**, and it measured the right thing for the question it
was asked: if you pick 5 pods at random, the tail across choices is
catastrophic. But there is exactly one group of 5 services and one group of 3
nodes. No subset is being chosen, so the tail across subset choices is not a
risk those groups carry.

`error_ratio` at 5 services has a peer baseline of 51.82 and a fault of 3331.63.
A threshold above 52 separates them with room to spare. Under `MIN_PEERS = 12`
that pair is refused unmeasured.

**This is an observation, not a mechanism, and it is deliberately not being
promoted to one.** The obvious story - peers must be *exchangeable*, and 12 pods
of one shape are more exchangeable than 5 heterogeneous services, which is why
the service baseline is 51.82 rather than 5 - is exactly the shape of the three
mechanisms that turned out wrong. It gets its own prediction file and its own
run before it gets believed, and `MIN_PEERS = 12` stands until then.

## Owed before any threshold is written

1. **The simulator defect.** `_node_disk()` never calls `_baseline()`, so
   `NOISE[DISK_USED] = 0.004` and `SEASONAL_AMPLITUDE[DISK_USED] = 0.01` are
   declared and unreachable. `disk_ratio` cannot be calibrated until node disk
   is derived from its pods' samples. The fix changes a ground truth the 8/8
   `disk_pressure` alert gate was proven against, so it requires that gate
   re-run.
2. **The coverage guard that would have caught it.** The module docstring says
   *every* series carries seasonality and noise, citing
   `test_simulator_data.py`. That test asserts it for two series - `checkout`
   cpu and summed latency. Disk was never in scope.
