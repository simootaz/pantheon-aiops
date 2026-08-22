# Experiment B, re-run under asserted isolation — 2026-08-22

The first two runs measured four of five baselines under a reset that never
cleared (see `04` and `05`). This is the re-run, and the first version of these
numbers I would defend.

## Isolation, measured rather than assumed

- `MetricsGenerator.reset()` before every scenario, raising
  `PushgatewayNotClearedError` if any series survives the delete.
- Each row records `window_start` and `fault_from`, so contamination is
  checkable after the fact instead of argued absent.
- Each metric's first baseline sample is compared against the previous
  scenario's final value.

**Result: `carried=0` on all thirty metric-scenario pairs.** No series repeated
the previous run's last value at any window's first sample.

## Scored by separation, per scenario's own metric

| scenario | metric | peers | baseline | fault | separation | |
|---|---|---|---|---|---|---|
| `bad_deploy_5xx` | error_ratio | 5 | 51.82 | 3331.63 | **64.3x** | detects |
| `flaky_test_storm` | ci_ratio | 5 | 19.04 | 950.86 | **50.0x** | detects |
| `memory_leak` | memory | 12 | 3.94 | 30.35 | **7.7x** | detects |
| `noisy_neighbor` | latency | 12 | 5.86 | 14.21 | **2.4x** | detects |
| `disk_pressure` | disk_ratio | 3 | 0.00 | 1569.54 | degenerate | **refused** |

`noisy_neighbor` also separates 3.6x on cpu.

## The retraction of a retraction

`noisy_neighbor` was previously scored a **MISS** at 0.8x - fault 17.09 against
a baseline of 22.76 - and that miss was explained as partial common-mode, since
node-c holds 4 of 12 pods.

With a working reset its baseline is **5.86** and it detects at 2.4x. The
partial-common-mode reasoning was never tested against clean data; it was fitted
to a contaminated baseline. It remains sound in principle and is not what
happened here.

## What stands

**Peer-relative detects 4 of 5.** It needs no window and no period estimate,
which is the temporal path's production blocker.

**`disk_pressure` is the one it cannot do**, and B4 predicted that scenario would
be the failure - for the wrong reason. Predicted: common-mode across nodes.
Actual: three peers is a degenerate estimator, which `MIN_PEERS = 12` refuses
outright. Its baseline of exactly 0.00 and its fault of 1569.54 are both the
floor speaking.

## Still open

The 5-peer groups (`error_ratio`, `ci_ratio`) carry baselines of 10 - 100 and
detect only because their faults are 50x larger. `MIN_PEERS = 12` currently
refuses them too - so on the measured rule, peer-relative detects **two** of five
(`memory_leak`, `noisy_neighbor`) and refuses the rest. The 5-peer results are
recorded as evidence, not as a licence to lower the minimum.
