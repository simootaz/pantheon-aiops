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
