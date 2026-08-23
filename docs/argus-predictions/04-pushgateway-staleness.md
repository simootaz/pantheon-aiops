# Predictions 4 — written BEFORE the measurement, 2026-08-21

Testing whether the mechanism EXISTS before testing whether it produces an
effect. No scenario run needed.

## A distinction I want on record first

The frozen data observed earlier is **not** evidence of carry-forward. The
pushgateway was never deleted in that case - it kept serving its last values and
Prometheus kept scraping them, so those were genuine repeated samples of a
static value. Carry-forward after a DELETE is a different mechanism, and the
frozen-data observation says nothing about it either way.

I had been treating them as the same thing. They are not, and the whole
contamination hypothesis rests on the second, which has not been tested.

## Q1 — does DELETE stop the pushgateway serving those series?

Predicted: **yes, immediately.** `pantheon_` series count drops to 0 on the
first `/metrics` fetch after the DELETE, under one second.

FALSIFIED IF the series persist. That would make the settle useless regardless
of what Prometheus does.

## Q2 — does Prometheus carry the last value forward?

This is the one that matters, and my prediction disagrees with the hypothesis.

Prometheus writes a **staleness marker** when a series that was present in a
previous scrape is absent from a successful scrape. Queries after that marker
return nothing rather than the last value. So:

- Predicted: values stop **within 1-3 seconds** of the DELETE - one or two
  scrape intervals - **not** the 5-minute lookback delta.
- Predicted: an instant query 10s after the DELETE returns **no result**.
- Predicted: `query_range` across the DELETE shows samples up to the delete and
  none after, with the gap starting within ~2s.

FALSIFIED IF values continue for anything approaching 5 minutes. That is
carry-forward, and it would mean the lookback delta is filling the gap.

The two can diverge and both are measured: the staleness marker is about what
the TSDB stores, the query result about what a reader sees.

## Q3 — does the frozen-data refusal fire on its first live case?

The pushgateway currently holds series that have been static for hours. The
refusal added to the sweep harness counts distinct values on a reference series
and aborts below 10.

Predicted: it **fires** on the current window - distinct count 1.

FALSIFIED IF it passes, which would mean the refusal does not catch the exact
case it was written for.

## The consequence, stated before the result

**If Q2 is falsified** - carry-forward real at ~5 minutes - then
`noisy_neighbor`'s 480s baseline window is majority-contaminated by the
preceding scenario's fault, four of five baselines in `peer2.txt` are void, and
Experiment B re-runs with isolation: a longer settle, a fresh pushgateway
container, or run windows offset past the lookback delta.

**If Q2 holds** - staleness works within seconds - then the 20s settle is more
than adequate, retained-series contamination is ruled out as the mechanism, and
the 22.76 anomaly still has no supported explanation. It stays open; a fourth
guess is not offered.

---

# Result — measured 2026-08-21

## Q1 — FALSIFIED

Predicted: the DELETE stops the pushgateway serving those series, immediately.

```
before                            119 pantheon_ lines
DELETE /metrics/job/pantheon_sim  -> 202   still serving 119
DELETE /metrics/job/pantheon-sim  -> 202   still serving 0
```

The group is `pantheon-sim`. Every reset in the repository deleted
`pantheon_sim`. A pushgateway answers **202 Accepted** for a group that does not
exist, so every reset succeeded loudly and cleared nothing - introduced
2026-08-17 in the same commit as the push path, fixed 2026-08-21, live in every
calibration harness and inside a gate passing 8/8 throughout.

The prediction was falsified in a way I had not considered: I predicted the
DELETE would work and asked what Prometheus did afterwards. The DELETE was the
defect.

## Q2 — CONFIRMED, once it was testable at all

Predicted: values stop within 1-3 seconds via staleness, not the 5-minute
lookback. Measured after a **real** delete: **0 series at t+2s.**

There is no carry-forward. The contamination hypothesis that motivated this
whole test was wrong about its mechanism while being right that contamination
existed.

## Q3 — CONFIRMED

The frozen-data refusal fired on its first live case: 12 series, 1 distinct
value, refused. It caught exactly what it was written for.
