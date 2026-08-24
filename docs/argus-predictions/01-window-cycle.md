# Predictions, written BEFORE the measurement — 2026-08-20

Design: ONE wall-paced baseline run at 630x for 480s wall (3.5 simulated days),
timestamps recorded. Cadence is held constant so speed is not a variable; only
W varies. One simulated day = 86400/630 = 137.1 wall seconds.

W is chosen so the window spans a stated fraction of the diurnal cycle, and
every W is >= 34 samples so a small-window estimator instability cannot be
mistaken for the effect.

| cycle fraction | W (samples) | judged samples |
|---|---|---|
| 0.25 | 34  | ~446 |
| 0.50 | 69  | ~411 |
| 0.66 | 90  | ~390 |
| 1.00 | 137 | ~343 |
| 2.00 | 274 | ~206 |

## Prediction 1 — the window/cycle shape

`error_ratio` max |z| peaks near 0.66 cycles and collapses at whole multiples.

| fraction | predicted |z| |
|---|---|
| 0.25 | 3 – 8 |
| 0.50 | 10 – 18 |
| 0.66 | **18 – 25** (anchored: 20.22 already observed at this exact W and speed) |
| 1.00 | 3 – 8 |
| 2.00 | 2 – 6 |

FALSIFIED IF: no peak near 0.66, or no collapse at 1.00 and 2.00. A monotonic
rise with W, or a flat line, kills the seasonal-window story.

## Prediction 2 — amplitude drives which metric suffers

`request_rate` alone (seasonal amplitude 0.55) should peak HARDER than
`error_ratio` (residual ~0.35, being 0.55 denominator against 0.20 numerator).

Predicted `request_rate` peak at 0.66 cycles: **> 25**, and above whatever
`error_ratio` reaches at the same W.

FALSIFIED IF: `request_rate` peaks at or below `error_ratio`. That would leave
the window shape intact but kill the amplitude explanation for which metric
is affected.

## Prediction 3 — the one that matters most

Whole-cycle windows are stable for EVERY metric, not only `error_ratio`.

`latency` (amplitude 0.25) and `ci_ratio` (0.30) should show the same shape,
weaker: peak 6 – 12 at 0.66 cycles, and materially lower (< 5) at 1.00 and 2.00.

FALSIFIED IF: `latency` and `ci_ratio` are flat across all fractions. That would
mean the gauges are stable for some other reason and W=90 was fine for them.

IF CONFIRMED: every threshold in the table is an artifact of where its
measurement sat in the cycle. W=90 was never right - it was lucky for the
metrics with small swings, and `error_ratio` is not a special case but the
loudest instance of a general defect.

---

# Result — measured 2026-08-20

```
metric           0.25cyc    0.50cyc    0.66cyc    1.00cyc    2.00cyc
W (samples)           34         69         91        137        274
error_ratio        11.10      18.43      22.14       6.57       5.89
request_rate       12.97       8.03       4.84       1.72       1.58
latency             6.29       4.21       3.99       3.31       2.72
ci_ratio            6.30       4.60       4.71       3.38       3.05
cpu                 5.48       6.63       5.71       2.15       2.01
```

## P1 — shape confirmed, magnitude missed

Peak at 0.66 (22.14, predicted 18-25) and collapse at whole cycles (6.57 and
5.89, predicted 3-8 and 2-6). But **0.25 came in at 11.10 against a predicted
3-8** - outside the range, and visible only because the number was written
first. Read afterwards it would have been absorbed as "low".

## P2 — FALSIFIED

`request_rate` has the largest seasonal amplitude (0.55) and shows **no peak at
all**: a clean monotonic decline, 12.97 to 1.58, peaking at the *smallest*
window. It never exceeds `error_ratio`. Whatever makes `error_ratio` peak
mid-cycle is not seasonal amplitude, because the metric with the most
seasonality does not do it.

No replacement mechanism is proposed here. The ratio structure is the obvious
candidate, and obvious candidates are what produced the aliasing story.

## P3 — shape falsified, substance confirmed

`latency` and `ci_ratio` show **no peak at 0.66** - they decline monotonically,
so that half is wrong. The half flagged as mattering most holds, and holds for
every metric:

| metric | worst sub-cycle | best whole-cycle | improvement |
|---|---|---|---|
| `request_rate` | 12.97 | 1.58 | **8.2x** |
| `error_ratio` | 22.14 | 5.89 | 3.8x |
| `cpu` | 6.63 | 2.01 | 3.3x |
| `latency` | 6.29 | 2.72 | 2.3x |
| `ci_ratio` | 6.30 | 3.05 | 2.1x |

**Every metric is quietest at whole-cycle windows.** W=90 at 630x sits at 0.66
of a cycle - the worst point for `error_ratio` and a middling one for the rest.
Any threshold table built on W=90 would have encoded where each metric's
measurement happened to fall in the cycle.
