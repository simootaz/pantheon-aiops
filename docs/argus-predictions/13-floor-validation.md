# Predictions 13 — is the scale floor validated, and is `memory` a threshold at all?

Written BEFORE the measurement, 2026-08-24, on `feature/argus-floor-validation`.

## Why this lands before any detection code

The thresholds in the matrix are held out from the runs the floor was fitted to.
**The floor is not held out from anything.** It was derived once, from runs 1-5,
and every threshold is a number of scale units — so if the floor moves, all six
move with it.

Record 09 is what that looks like when nobody checks: `min(scale)/median(scale)
>= 0.259` accepted 35 groups with zero blow-ups on the data it was fitted to,
and let **seven** through on fresh runs.

## The measurement

1. **Split-half.** Re-derive the floor from runs 1-5 and from runs 6-10 of the
   committed ten-run set, from the recorded windows.
2. **Out-of-sample.** Five fresh baseline runs at 630x for 480s, isolation
   asserted, and the floor derived from those alone.
3. **Per-run.** The floor from each single run, to see convergence.
4. **Consequence.** Every committed threshold re-evaluated under each floor, so
   the question "does a floor difference matter" is answered in thresholds and
   not in percentages.

---

## P1 — the halves agree

> The p05 floors from runs 1-5 and runs 6-10 differ by **under 10%** for all six
> metrics.

**Falsified if** any metric differs by 10% or more.

## P2 — the fresh set agrees

> The floor derived from five fresh runs differs from the committed floor by
> **under 15%** for all six metrics.

**Falsified if** any metric differs by 15% or more. This is the one that matters:
the halves share a session, a stack and a clock, and agreeing with yourself is
not validation.

## P3 — convergence

> A single run's floor is within **25%** of the five-run value for at least four
> of six metrics, and **N = 3** brings all six inside 15%.

**Falsified if** fewer than four single runs land inside 25%, or any metric is
still outside 15% at N = 3.

## P4 — no committed threshold changes by more than one ladder step

The consequence test, stated in thresholds rather than percentages.

> Re-deriving each threshold under the fresh-set floor moves **none** of the six
> by more than one ladder step, and leaves every scenario's detection margin
> above 2x.

**Falsified if** any threshold moves by two steps or more, or any margin falls
to 2x or below.

---

## `memory`, which may not be a threshold problem at all

`memory` clears its observed maximum by **1.005**. An unrelated scenario already
reaches 3.92 against a threshold of 4.0. There is no headroom to nudge.

The suspicion worth testing: **`memory`'s peer maximum is not a noise tail, it
is a structural constant.** The twelve pods span 0.33 to 2.52 GB, and
`search-2f6b8c-a1` at 2.52 sits (2.52 - 0.94) / 0.459 = **3.44** robust
deviations from the group median by arithmetic alone, before any noise. The
measured maxima across eight runs are 3.91, 3.92, 3.92, 3.94, 3.94, 3.94, 3.98,
3.99 — a spread of 2%, which is not what a tail looks like.

If that is what is happening, the number is a property of the topology, not of
the data, and no amount of measurement makes it a safe threshold: it would move
the moment a pod is resized or a replica is added, and it would move without any
fault occurring.

## P5 — the test that separates a constant from a tail

> For `memory`, the **same pod** attains the maximum z in at least **9 of 10**
> runs. For `latency` and `cpu`, the attaining pod varies across at least **3**
> distinct pods.

**Falsified if** `memory`'s attaining pod varies across three or more pods, or
if `latency` and `cpu` are each dominated by a single pod in 9 of 10 runs.

## P6 — and what it does to the fresh runs

> `memory`'s per-run maximum on the five fresh runs stays inside **3.85 – 4.05**,
> and its floor engagement stays under **8%**, because a structural maximum
> occurs at ordinary scale rather than at a collapsed one.

**Falsified if** any fresh run's maximum falls outside 3.85 – 4.05.

---

## Stated in advance: what would mean `memory` needs different treatment

**If P5 holds** — one pod attains the maximum in 9 of 10 runs — then `memory`'s
threshold is a topology constant plus 0.5%, and tuning the number is the wrong
response. Three treatments, in the order I would prefer them:

1. **Raise it against the fault budget rather than the baseline.** The fault
   reaches 33.37, so a threshold of 8 still leaves 4.2x. That trades sensitivity
   for stability and is honest about which is scarce.
2. **State it as topology-bound.** `MetricThreshold.conditions` would have to
   name the pod set, and any change to `PODS` invalidates it. That is a real
   maintenance burden and should be written down as one.
3. **Compare `memory` differently.** If the peer maximum is dominated by one
   permanent outlier, peer comparison is answering "which pod is biggest",
   which is constant and known. The temporal path, which record 07 measured at a
   baseline of 2.04 for `memory`, does not have this problem.

**If P5 fails** — the attaining pod varies — then the tight spread is a genuine
property of the distribution, 4.0 is a real threshold, and only its headroom is
uncomfortable. It would then need the same treatment as `ci_ratio` and
`error_ratio`, whose margins are 1.036 and 1.033: a stated false-positive rate
rather than a promise of silence.

## What each outcome licenses

| outcome | what it licenses |
|---|---|
| P1, P2, P4 hold | The floor is validated out-of-sample and the matrix stands. Detection code proceeds. |
| P2 fails | Every threshold rests on an unvalidated scale. The matrix is withdrawn until the floor is derived over enough runs to be stable, and record 09 repeats itself. |
| P4 fails | The floor's variation is large enough to move thresholds. The floor needs more runs, or a less sensitive statistic than a quantile. |
| P5 holds | `memory` is treated as topology-bound, by one of the three routes above, and the choice is recorded rather than assumed. |

No detection code is written before this is scored.

---

# Result — PENDING

The measurement has not been run. Predictions committed first; this section is
a placeholder so that "not yet scored" is a state the repository states.
