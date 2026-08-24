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

# Result — measured 2026-08-24

Fresh baseline run, seed 20260825, `kept_up=True`, `degraded=False`. Raw data in
`data/threshold-validation.json`.

## The fitted threshold did not survive

| threshold | accepts | blow-ups | worst accepted |
|---|---|---|---|
| **0.259** (fitted) | 32 | **7** | 12.34 |
| 0.300 | 29 | 5 | 12.34 |
| 0.350 | 20 | **1** | 9.42 |
| 0.400 | 20 | **1** | 9.42 |
| 0.500 | 20 | **1** | 9.42 |
| `n >= 12` | 6 | **4** | 12.66 |

0.35, 0.40 and 0.50 are identical because no group has a `min/median` between
0.345 and 0.60 — the distribution has a gap there, so those three are one
threshold wearing three numbers.

## P1 — direction right, range wrong

Predicted 1 – 6 blow-ups at the fitted threshold; measured **7**. The
falsification condition was zero blow-ups and it did not fire, so the claim that
a boundary drawn at the worst point of one sample would not generalise is
confirmed. The range still missed, by one.

**Third occurrence of the same defect.** 07's P4 (`latency`, 4.77 against "at
least 5x" with a falsifier at 2.42x), 08's P4 (passed its falsifier, failed its
purpose), and now this. The pattern is a point prediction and a falsification
condition that disagree about what counts as failure, which leaves the scoring
to judgement. Recorded as its own entry rather than as a third footnote.

## P2 — FALSIFIED, and it decides the outcome

Predicted: 0.40 accepts zero blow-ups and at least 15 groups. Measured **20
groups and one blow-up** — `memory:8:raw`, at 9.42.

That group has `min/median = 0.8102`, the third most stable scale in the whole
run. **Scale stability is necessary and not sufficient**, and no threshold
tested reaches zero.

Per the table committed before the run, P2 falsified means: no safe threshold
has been found, and `MIN_PEERS = 12` stays. It stays.

## P3 — HIT

Rank correlation against `max abs z` on the fresh groups: `min/median`
**-0.923** (predicted -0.85 to -0.97), group size **-0.530** (predicted below
0.7 in magnitude). The property replicates and continues to beat the count by a
wide margin.

## P4 — three clauses hit, one missed, and the miss withdraws an explanation

| clause | predicted | measured | |
|---|---|---|---|
| normalised dispersion | below 0.01 | **0.000000** for all five groups | hit |
| raw pod dispersion | 0.45 – 0.85 | memory 0.487, cpu 0.607, latency 0.689 | hit |
| raw service dispersion | above 0.05 | error_ratio **0.0083**, ci_ratio **0.0197** | miss |

The first two clauses were the ones that mattered for 08. They confirm the
transform does exactly what both documents claim - it removes between-member
level differences and leaves the members at an identical level, measured rather
than argued. **08's P1 and P2 are un-provisioned on that basis.**

The third clause withdraws the explanation 08 offered. `ci_ratio`'s services
differ in realised level by 2.0%, not by the large amount 08's reasoning
required, so "identical base levels do not give identical realised medians" is
not why `ci_ratio` moved 77.45 to 32.78. That explanation is wrong and is
withdrawn.

What replaces it is not being adopted here. Between-member spread enters both
the numerator of a peer z (how far the outlying member sits from the median) and
its denominator (the MAD), and which one wins should depend on whether the
spread dominates the noise. Pods spread 49 – 69% and normalising made them
worse; services spread 0.8 – 2.0% and normalising made `ci_ratio` better. That
account fits both directions, which is exactly what the three withdrawn
mechanisms also did. It gets a prediction file before it gets believed.

---

## Run-to-run stability, three data points now

| group | n | run 08 | run 09 | change |
|---|---|---|---|---|
| `memory:raw` | 12 | 3.95 | 4.03 | +2% |
| `cpu:raw` | 12 | 3.56 | 3.28 | -8% |
| `latency:raw` | 12 | 5.56 | **8.42** | **+51%** |
| `error_ratio:raw` | 5 | 25.73 | 38.65 | +50% |
| `ci_ratio:raw` | 5 | 77.45 | 32.34 | **-58%** |

With 06's 51.82, `error_ratio` has now been measured at 51.82, 25.73 and 38.65 —
a 2x span across three runs. 08's P5 holds on a third point.

`latency:raw` crossing from 5.56 to 8.42 is the result that most constrains what
comes next: a real 12-peer group, the kind actually deployed, moved 51% between
two runs differing only in seed and clock.

## A number I declared and did not derive

`BLOWUP = 8.0` separates "fine" from "blew up" throughout this analysis, and I
chose it. Several verdicts sit within 20% of it — `latency:raw` at 8.42,
`memory:8:raw` at 9.42, `memory:normalised` at 8.96 — so the accept and reject
counts above are sensitive to a threshold nothing derived.

The rank correlations do not depend on it, which is why they carry the
conclusion here and the counts do not. Stated because this repository's rule is
that every number in the docs is derived, and this one is not.

## Where this leaves the peer path

- **`MIN_PEERS = 12` stays**, unchanged, and is now known to be a proxy rather
  than the real condition. It is a bad proxy: on this run `n >= 12` admitted 6
  groups and 4 of them blew up.
- **The property is real and replicates** (-0.923 against -0.530 for size) but
  no threshold on it is safe yet, and one group with a near-perfect scale still
  failed.
- **Peer comparison is not yet calibratable for any group**, which the threshold
  matrix has to state rather than work around.
