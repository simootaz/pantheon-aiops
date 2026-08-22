# Predictions 2 — written BEFORE the measurements, 2026-08-20

## Experiment A: are there two effects?

Small-W estimator noise depends on W in **samples**. Mid-cycle drift depends on
W as a **fraction of the cycle**. Hold the fraction constant and vary the sample
count by changing speed; if one number explains the data, the other is not
acting.

Three wall-paced 480s baselines at 228x, 630x (already run), 2500x. One
simulated day is 379.0s, 137.1s and 34.6s of wall clock respectively, so:

| fraction | W at 228x | W at 630x | W at 2500x |
|---|---|---|---|
| 0.25 | 95 | 34 | 9 |
| 0.50 | 189 | 69 | 17 |
| 0.66 | 250 | 91 | 23 |
| 1.00 | 379 | 137 | 35 |
| 2.00 | (too long for 480s) | 274 | 69 |

### A1 — `error_ratio` at fixed fraction 0.66

W is 250, 91 and 23 samples for the same 0.66 of a cycle.

- **If drift alone**: all three land in **15 - 25**. Anchored by 22.14 measured
  at 630x/W=91.
- **If estimator noise also acts**: 2500x (W=23) comes in **above 25**, and
  228x (W=250) **below 15**, ordering by sample count rather than by fraction.

Predicted, stating the belief rather than hedging: **two effects**. 228x/W=250
lands 12 - 20, 630x/W=91 lands 18 - 25, 2500x/W=23 lands **above 28**.

### A2 — `request_rate` at fixed fraction 0.25

It declined monotonically with W and peaked at the smallest window, which is the
signature of estimator noise rather than drift.

- W = 95 (228x): predicted **2 - 6**
- W = 34 (630x): 12.97 measured
- W = 9 (2500x): predicted **above 20**

FALSIFIED IF these are equal within a few units. Equal values at one fraction
across a 10x range of sample counts would mean sample count does not matter,
and the single-effect reading is right.

### A3 — the consequence if two effects hold

Whole-cycle windows would then be doing two jobs at once by coincidence: they
cancel drift *and* they happen to be large. The design must state which effect
each choice addresses, because a fix justified by the wrong one of two effects
is exactly where the aliasing story left us.

---

## Experiment B: peer-relative comparison

Compare a series against its peers at the same instant instead of against its
own past. Seasonality is common-mode across peers, so it cancels with no window
and no period estimate.

`z_peer(pod) = (value(pod) - median(peers)) / (1.4826 * MAD(peers))` at each
scrape, peers being the other pods of the service, services of the cluster, or
nodes as appropriate to the metric.

### B1 — clean baseline

Predicted peer-relative max |z| on a clean baseline: **2 - 5** for every metric,
and **materially below** the temporal figures at the same instant. Pods differ
by their per-pod seed only, so the spread should be small and stationary.

FALSIFIED IF peer-relative baseline |z| exceeds 8, which would mean pods differ
enough at baseline that divergence cannot be read against them.

### B2 — per scenario, per metric

Peer-relative detection should work exactly where the fault is a divergence and
fail where it is common-mode.

| scenario | shape | metric | predicted peer z during fault |
|---|---|---|---|
| `noisy_neighbor` | one node diverges | latency | **> 15**, strong |
| `memory_leak` | one pod diverges | memory | **> 20**, strongest |
| `bad_deploy_5xx` | one service diverges | error_ratio | **> 10** |
| `flaky_test_storm` | one service diverges | ci_ratio | **> 10** |
| `disk_pressure` | node-a fills, others do not | disk_ratio | **> 15** |

### B3 — the honest failure

A fault hitting all peers equally must be invisible peer-relatively. There is no
such scenario in the current five, so this is predicted as a **constructed**
check rather than observed: scaling one metric on every pod simultaneously
should produce peer |z| **below 3** while temporal z rises.

FALSIFIED IF a synthetic all-peers fault still produces peer |z| above 5.

### B4 — the expected conclusion

Both comparisons, with each Finding stating which produced it. Peer-relative
for divergence, temporal for common-mode. Predicted, so it can be wrong:
peer-relative detects **4 of 5** scenarios above threshold; `disk_pressure` is
the one at risk of being common-mode, and if all four nodes fill together its
peer z lands **below 5** while its temporal z stays high.
