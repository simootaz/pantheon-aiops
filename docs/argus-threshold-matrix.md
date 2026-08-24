# Argus threshold matrix

Derived 2026-08-24. Every number here was measured against the live stack, and
every one is re-derivable from the records in `docs/argus-predictions/`.

The values live in `agents/anomaly/calibration.py`; this is the derivation.

## How each number was arrived at

**Ten baseline runs** at 630x compression for 480s each, isolation asserted per
run - `reset()` raises if series survive, and the first sample of every run is
compared against the previous run's last (`carried = 0` throughout).

**Runs 1-5 set the scale floors. Runs 6-10 set the thresholds.** The split
matters: a floor chosen from a scale distribution and then judged on the same
runs is fitted to its own evidence. Every threshold below is the smallest ladder
value with **zero exceedances on runs the floor never saw**.

**The false-positive bound is the rule of three.** Zero events in n samples puts
the rate below 3/n at 95% confidence - about **1.1e-3** on 2760 held-out
instants. Prediction 11 called this "1e-4"; that was the criterion used to pick
a threshold, not a rate anyone measured. A rate of 1e-4 cannot be measured from
this many samples, only bounded above.

## The matrix

| metric | members | scale floor (metric units) | floor engages | threshold | held-out max abs z | margin |
|---|---|---|---|---|---|---|
| `memory` | 12 pods | 4.084e+08 bytes | 5.2% | **4.0** | 3.98 | 1.005 |
| `cpu` | 12 pods | 0.1746 cores | 4.8% | **3.5** | 3.01 | 1.163 |
| `latency` | 12 pods | 0.03933 s | 4.6% | **6.0** | 5.10 | 1.176 |
| `disk_ratio` | 3 nodes | 2.953e-05 ratio | 5.3% | **100.0** | 92.77 | 1.078 |
| `ci_ratio` | 5 services | 8.634e-04 ratio | 5.3% | **20.0** | 19.30 | 1.036 |
| `error_ratio` | 5 services | 1.920e-05 ratio | 5.3% | **25.0** | 24.19 | 1.033 |

Not calibrated, and refused rather than defaulted: `request_rate` and
`restarts`. Both are counters, and a rate's noise depends on the compression it
was measured at - so a single number for either means nothing across a gate that
runs each scenario at a different speed. `threshold_for` raises for them.

## Detection: all five scenarios, measured under these floors

Fault z re-measured 2026-08-24 under the same floors as the thresholds. The
earlier figures were taken under `min(|value|) * 1e-3` and could not be divided
by these thresholds - that would be two statistics in one ratio.

| scenario | metric | threshold | fault abs z | margin | verdict |
|---|---|---|---|---|---|
| `disk_pressure` | disk_ratio | 100.0 | 10117.37 | **101.2x** | detectable |
| `bad_deploy_5xx` | error_ratio | 25.0 | 701.39 | **28.1x** | detectable |
| `flaky_test_storm` | ci_ratio | 20.0 | 379.33 | **19.0x** | detectable |
| `memory_leak` | memory | 4.0 | 33.37 | **8.3x** | detectable |
| `noisy_neighbor` | latency | 6.0 | 15.74 | **2.6x** | detectable, thinly |

**All five are detectable**, which no earlier configuration achieved. 06 put it
at 2 of 5, and both of the reasons turned out to be artifacts: the peer bound
was under-sampled (record 10) and the scale floor was mis-set (this matrix).

## What this configuration does NOT do

**It does not separate one scenario from another.** These thresholds separate a
fault from a clean baseline, and nothing more. Measured across all five
scenarios, the worst reading of each metric on a scenario it is *not* the target
of:

| metric | worst non-target reading | threshold | fires? |
|---|---|---|---|
| `latency` | 23.85 (during `bad_deploy_5xx`) | 6.0 | **yes** |
| `cpu` | 8.93 (during `noisy_neighbor`) | 3.5 | **yes** |
| `disk_ratio` | 60.27 (during `memory_leak`) | 100.0 | no |
| `ci_ratio` | 18.15 (during `memory_leak`) | 20.0 | no |
| `error_ratio` | 23.60 (during `disk_pressure`) | 25.0 | no |
| `memory` | 3.92 (during `disk_pressure`) | 4.0 | no |

`latency` firing during a bad deploy is correct - the scenario steps latency
alongside errors, and the alert rules say so. But **Argus will emit several
Findings for one incident**, and deciding which is the cause is Zeus's and
Delphi's problem, not a threshold's. Anything reading a single Finding as a
diagnosis is reading it wrong.

**Three thresholds have almost no headroom.** `memory` clears its observed
maximum by 1.005 and the worst unrelated scenario reaches 3.92 against a
threshold of 4.0 - a 2% gap. `error_ratio` (1.06x) and `ci_ratio` (1.10x) are
similar. These will produce occasional false positives, and the rate above is an
upper bound on how often, not a promise of silence.

**It is valid only at the conditions measured.** 630x compression, 480s runs,
this topology, this generator. A threshold is a number about a distribution, and
nothing here establishes that the distribution is the same at another speed or
on another cluster. `MetricThreshold.conditions` carries the conditions for
exactly this reason.

**`disk_ratio` rests on three members.** That is now permitted because the
evidence says count is not the safety variable - but three is where a MAD is
weakest, and its threshold of 100 against a held-out maximum of 92.77 is the
widest absolute spread in the table.

## What replaced MIN_PEERS

`MIN_PEERS = 12` was an empirical count from a sweep over random pod subsets. It
is now 3, which is arithmetic - a median and a MAD over fewer than three values
describe nothing - and the safety rule moved to two places:

1. **A calibrated threshold**, which a metric either has or does not.
   `threshold_for` refuses rather than defaulting.
2. **`MIN_CALIBRATION_RUNS = 4`**, because a bound from one run is one sample of
   a distribution whose worst case is what matters. Prediction 11 measured a
   pooled bound at 1e-3 failing to cover its own worst run for five of six
   groups.

Records [08](argus-predictions/08-peer-scale-stability.md),
[09](argus-predictions/09-threshold-validation.md) and
[11](argus-predictions/11-min-peers-decision.md) each tested whether peer count
is the variable. It is not: a three-member group is calibrated and detects at
101x, two of three twelve-member groups fail a test a five-member group passes,
and peer count correlates with the threshold a group needs at -0.600.

## Open

- **The floor is a quantile, and 5% is a choice.** p05 was picked because it
  makes engagement stated rather than accidental - the old heuristic engaged
  46.9% of the time for `disk_ratio` and 0% for four other metrics, and nobody
  knew. A different quantile is defensible; an unmeasured constant is not.
- **No out-of-sample confirmation of this floor.** The thresholds are held out
  from the floor's runs, but the floor itself has not been re-derived on fresh
  data. Record 09 is what happens when a fitted number is not validated.
- **`noisy_neighbor` at 2.6x** is the thinnest real margin, and peer comparison
  is structurally poor at it: the fault hits several pods of one node together,
  which is partly common-mode and drags the peer median with it.
