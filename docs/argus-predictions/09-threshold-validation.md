# Predictions 9 — does the fitted threshold survive a fresh run?

Written BEFORE the measurement, 2026-08-24, on `feature/argus-peer-exchangeability`.

## Why this exists

08 found that `min(scale) / median(scale)` predicts peer-comparison blow-ups far
better than group size does — rank correlation **-0.932** against **-0.476** —
and that a threshold of **0.259** accepted 35 of 154 groups with zero blow-ups
where `n >= 12` accepted 6 and let 3 through.

That threshold was chosen after seeing the data, and it sits **exactly at the
maximum of the failing class**. It is the most overfit value available: one
group anywhere near the boundary moves it. A rule selected that way has not been
tested, it has been drawn around the points.

08 also left P1 and P2 provisional. Their pre-registered consequence fired when
P6 failed, and the argument for reading them anyway is a post-hoc rescue.

Same run answers both.

## The measurement

A fresh baseline-only run at 630x for 480s, with a **different subset seed**
(20260825, against 08's 20260824), so the group draws are not the ones the
threshold was fitted on. Timestamps recorded. Same statistic, same
`max abs z > 8` definition of a blow-up.

---

## P1 — the fitted threshold lets blow-ups through

> Applying `min(scale)/median(scale) >= 0.259` to the fresh groups accepts at
> least one group whose `max abs z` exceeds 8. Predicted **1 – 6** such
> failures among the accepted set.

Zero failures would mean a boundary fitted to the worst point of one sample
generalised exactly, which is not how a fitted boundary behaves.

**Falsified if** the accepted set has no blow-ups at all.

## P2 — a margin above the fitted point does survive

> `min(scale)/median(scale) >= 0.40` accepts **zero** blow-ups on the fresh run,
> and accepts at least 15 groups so the rule is not vacuous.

**Falsified if** 0.40 admits a blow-up, or admits fewer than 15 groups.

If both P1 and P2 land, the honest output is a threshold with a stated margin
and a stated cost, not the number that fitted best.

## P3 — the statistic's rank correlation holds

> Rank correlation between `min(scale)/median(scale)` and `max abs z` on the
> fresh groups lands in **-0.85 to -0.97**, and group size again correlates
> substantially worse — its magnitude below 0.7.

**Falsified if** the scale statistic falls below 0.80 in magnitude, or group
size matches it within 0.1.

## P4 — the pod normalisation does what 08 assumed

The direct re-test that 08's P6 failure demands, replacing the argument made
there.

> After normalisation, the between-member dispersion of a pod group —
> `1.4826 * MAD` of the members' own medians, over the median of those medians —
> is **below 0.01**, against **0.45 – 0.85** raw. And for the service groups it
> is likewise below 0.01 after normalisation, against a **raw value above 0.05**
> — which is the quantity 08's P6 assumed was near zero and never measured.

**Falsified if** normalised dispersion exceeds 0.01 anywhere, which would mean
the transform does not do what both documents claim.

If the raw service dispersion comes back above 0.05, then `ci_ratio`'s services
were never level-identical in practice, 08's P6 failed for the reason given, and
**P1 and P2 of 08 can be un-provisioned**. If it comes back near zero, the P6
explanation is wrong and 08's normalisation results need re-deriving.

---

## What each outcome licenses

| outcome | what it licenses |
|---|---|
| P1 and P2 hold | The property is real and the threshold needs a margin. `MIN_PEERS` is replaced by a scale-stability floor of 0.40 with its measured error rates stated. |
| P1 falsified | The boundary generalised, which is surprising enough to want a third run before believing it. No rule change on two runs. |
| P2 falsified | No safe threshold has been found yet. `MIN_PEERS = 12` stays, now with a known reason for its existence rather than a sweep. |
| P3 falsified | The statistic was an artifact of one run. Everything 08 concluded about property-over-count is withdrawn. |
| P4 falsified | The normalisation is not the manipulation both documents describe, and 08's P1/P2 stay provisional pending a redesign. |

`MIN_PEERS = 12` remains in force until this is scored. No threshold enters
`calibration.py` from this run.

---

# Result — PENDING

The measurement has not been run. Predictions committed first; this section is
a placeholder so that "not yet scored" is a state the repository states.
