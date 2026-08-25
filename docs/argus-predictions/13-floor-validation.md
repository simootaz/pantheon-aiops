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

# Result — measured 2026-08-24

Five fresh baseline runs at 630x for 480s, isolation asserted, on a stack
restarted between sessions. Raw data in `data/floor-validation.json`.

**The floor is validated. The matrix stands. `memory` is topology-bound.**

## P2 — HIT, and it is the one that mattered

| metric | committed floor | fresh p05 | differs | engagement |
|---|---|---|---|---|
| `memory` | 4.0836e+08 | 4.0825e+08 | **0.0%** | 5.1% |
| `cpu` | 0.17457 | 0.17457 | **0.0%** | 4.9% |
| `disk_ratio` | 2.9526e-05 | 2.9809e-05 | 1.0% | 4.9% |
| `latency` | 0.039331 | 0.040648 | 3.3% | 4.0% |
| `ci_ratio` | 8.6338e-04 | 8.9181e-04 | 3.3% | 4.8% |
| `error_ratio` | 1.9203e-05 | 1.8353e-05 | **4.4%** | 5.5% |

Predicted under 15%; the worst is 4.4%. Engagement came in at 4.0 – 5.5%
against the 5% the quantile was chosen to produce.

This is the opposite of record 09, where a fitted number looked perfect on its
own data and let seven blow-ups through on fresh runs. The difference is what
was fitted: 09 fitted a **boundary to the extreme point** of one sample, and a
boundary drawn at the worst observation cannot generalise. This fits a **robust
quantile of a bulk distribution** over thousands of instants, which is a
different kind of estimate and behaves like one.

## P4 — HIT

| metric | committed T | re-derived on fresh data | steps moved |
|---|---|---|---|
| `memory` | 4.0 | 4.0 | 0 |
| `cpu` | 3.5 | 3.5 | 0 |
| `latency` | 6.0 | 6.0 | 0 |
| `ci_ratio` | 20.0 | 20.0 | 0 |
| `error_ratio` | 25.0 | 25.0 | 0 |
| `disk_ratio` | 100.0 | **80.0** | 1 |

Five of six are identical. `disk_ratio` re-derives one step lower because this
run's maximum was 77.99 against the committed set's 92.77.

**The committed 100 stays.** A threshold has to clear the worst run observed
anywhere, not the worst run of the most recent five - and 92.77 is still the
worst. Taking 80 would be choosing the friendlier sample, which is the mistake
this whole sequence of records exists to avoid.

## P3 — first clause hit, second unmeasured

Single-run floors against the five-run value: all five runs inside 25% for
`memory`, `cpu`, `latency`, `ci_ratio` and `error_ratio`; four of five for
`disk_ratio`, whose worst single run was 28.6% out. Predicted at least four of
six metrics; six of six qualify.

The second clause — "N = 3 brings all six inside 15%" — **cannot be scored**.
Pooled floors at N = 3 are not the mean of three single-run floors; they need
the raw scale samples, and the harness dropped those before writing its output
to keep the file small. That is a harness defect, not a result, and it is named
rather than glossed.

## P1 — UNSCOREABLE

The stack was restarted between sessions and Prometheus lost the ten windows the
split-half needed. The check reported it as unavailable rather than inferring
anything.

Losing it costs little: the two halves shared a session, a stack and a clock, so
they were always the weaker test. P2 is the one that carries the conclusion.

## P6 — HIT

`memory`'s per-run maxima on the fresh runs: **3.913, 3.985, 3.985, 3.914,
3.916** - inside the predicted 3.85 – 4.05, with floor engagement at 5.1%
against a bound of 8%.

Two clusters a few parts per thousand wide, from five independent runs. That is
not a distribution with a tail.

## P5 — the half that decides `memory` holds; the control half misses

| metric | dominant member | runs | distinct members |
|---|---|---|---|
| `memory` | `search-2f6b8c-a1` | **5 / 5** | **1** |
| `cpu` | `search-2f6b8c-a1` | 3 / 5 | 2 |
| `latency` | `search-2f6b8c-b2` | 3 / 5 | 2 |
| `disk_ratio` | `node-c` | 2 / 5 | 3 |
| `ci_ratio` | `payments` | 2 / 5 | 3 |
| `error_ratio` | `payments` | 2 / 5 | 4 |

`memory` is unanimous and is the only metric with a single owner. The gradient
runs 1, 2, 2, 3, 3, 4 and `memory` sits alone at the end of it.

The control half missed: `latency` and `cpu` were predicted to spread across at
least three members and reached two. Their falsifier - each dominated by one
member in 9 of 10 runs - did not fire either, so the result sits in the gap
between the prediction and its refutation.

**That is the fourth occurrence of the defect recorded after the third**, and
recording it did not stop me writing it again. The falsifier here was aimed at
the strong opposite case rather than at the edge of the claim, which is the same
error in a new place. The claim should have read "fewer than three distinct
members" as its own refutation.

Worth stating plainly: `cpu` favouring the same pod in 3 of 5 runs is a weaker
version of the same structural effect. `search-2f6b8c-a1` holds 1.10 cores
against a group median of 0.59, so it is an outlier there too - just not one
that wins every time.

---

## What this licenses, per the table committed before the run

P2 and P4 hold, so **the floor is validated out-of-sample and the matrix
stands.** P5's deciding half holds, so **`memory` is treated as topology-bound**
and the choice is recorded rather than assumed.

### The treatment chosen, and the two rejected

`memory`'s maximum is a constant of the cluster: `search-2f6b8c-a1` holds 2.52
GB against a group median of 0.94, putting it (2.52 - 0.94) / 0.459 = **3.44**
robust deviations out by arithmetic, before any noise. The measured 3.91 – 3.99
is that constant plus a little.

**Chosen: make the dependency mechanical.** `PEER_TOPOLOGY_FINGERPRINT` records
the hash of the pod and node base values, and a guard fails the build if the
live cluster no longer matches. Resizing a pod or adding a replica now forces a
re-derivation instead of silently voiding a threshold. Verified against two
planted changes - the outlier pod grown by 1 MB, and a thirteenth pod added.

**Rejected: raising the threshold against the fault budget.** The fault reaches
33.37, so 8.0 would leave 4.2x and remove the headroom problem. But the factor
would be invented. Trying to derive it exposed that: a "minimum 4x detection
margin" rule sounds principled and would force `latency` down to 3.5 against a
baseline maximum of 5.16, which would fire constantly. A rule that cannot be
applied to the other five metrics is a justification, not a rule.

**Deferred: comparing `memory` temporally.** Record 07 measured its temporal
baseline at 2.04, and the temporal path has no structural-outlier problem at
all - each series is compared against its own history. That is the structural
fix. It is deferred because the temporal path needs a diurnal cycle of history
that production may not have, and moving one metric to a different comparison
is a design change rather than a calibration.

## A planting that passed and should not have

The first attempt at the topology plant reported exit 0 - a pass. The sed
pattern did not match the file, so nothing was ever changed and the guard was
never exercised. A plant that fails to plant looks exactly like a guard that
correctly stays green.

Caught only by checking `git diff --stat` before reading the exit code. The
second attempt printed the diffstat first, and both real changes went red.

> A planting is two assertions, not one: that the violation was introduced, and
> that the guard fired. Skip the first and the second is unfalsifiable.
