# Predictions 8 — is MIN_PEERS a count or a property?

Written BEFORE the measurement, 2026-08-24, on `feature/argus-peer-exchangeability`.

## The question

`MIN_PEERS = 12` came from a seeded sweep over **random subsets of pods** (03),
which measured the tail across subset *choices*. 07 then found that peer
comparison separates best on the 5-member service groups — 64.29x for
`error_ratio` — which the rule refuses unmeasured. If a fixed group of 5 is safe
where a sampled group of 5 is not, the rule is not a count and needs restating
as whatever property it is standing in for.

## The premise is wrong, and reading the topology first says so

The framing was that the fixed groups are *heterogeneous* — few services, each
different, and no cluster size fixes that. In this cluster the opposite holds,
by construction:

| group | members | base level |
|---|---|---|
| services, `error_ratio` | 5 | **0.004000 for every one** |
| services, `ci_ratio` | 5 | **0.020000 for every one** |
| nodes, `disk_ratio` | 3 | **0.34 for every one** |
| pods, `memory` | 12 | 0.33 – 2.52 GB, a **7.6x** range |
| pods, `latency` | 12 | 31 – 210 ms, a **6.8x** range |
| pods, `cpu` | 12 | 0.19 – 1.10 cores, a **5.8x** range |

`error_rate` is `rps * 0.004` per pod and `error_ratio` divides by `rps`, so the
constant survives aggregation exactly. The small groups are perfectly
exchangeable; the large ones are not.

And the sign runs the wrong way for exchangeability as the explanation. The
**homogeneous** groups have the worst peer baselines (51.82, 19.04, degenerate);
the **heterogeneous** ones have the best (3.94, 5.86). So the story named in 07
— peers must be exchangeable — is not merely untested, it is contradicted by the
topology before any run.

## The mechanism this leaves, stated so it can lose

Peer z divides by `1.4826 * MAD` estimated across members **at one instant**.
With heterogeneous members the between-member spread inflates that scale, and z
is bounded by construction: `memory`'s most extreme pod is
(2.52 - 0.94) / 0.459 = 3.44, against a measured baseline of 3.94.

With homogeneous members the scale is whatever the noise happens to be, and at
small n the MAD **is itself a noisy estimate with a floor at zero**. Three of
five members landing close together makes the denominator small, and nothing
makes it large. The failure is one-sided, which is why the sweep's tail was
catastrophic while its median looked survivable.

If that is right, the rule is about **scale stability**, a property, and the
count is only how this cluster happens to achieve it.

---

## The design: 2x2, because size and homogeneity are confounded again

Small groups are homogeneous and large groups are heterogeneous, so no
comparison between them can separate n from exchangeability. The confound is
breakable by *making* a group homogeneous: divide each member's series by its
own median over the run, so every member sits at 1.0 and only noise remains.

| | raw (as measured) | normalised (made exchangeable) |
|---|---|---|
| **n = 12** | pods today | pods, level removed |
| **n = 5** | seeded random pod subsets | same subsets, level removed |

One baseline-only run at 630x for 480s. **Start and end timestamps recorded this
time** — they were not stored for 07's baseline run, which is the same lapse the
`data/README.md` warns about in writing, and it is why this needs a fresh run
rather than a re-query.

---

## P1 — normalised-12 stays good

> Maximum peer baseline abs z for normalised 12-pod groups lands in **3 – 6**,
> statistically indistinguishable from raw-12 (3.94 for memory, 5.86 for
> latency).

Twelve members at 1.0 plus noise give a MAD that estimates the noise well, so z
is near-standard-normal and its max over a few thousand windows is around 4.

**Falsified if** normalised-12 exceeds 10 for any of memory, cpu, latency.

## P2 — normalised-5 is worse than raw-5

> Over seeded random 5-pod subsets, the **median** maximum abs z is **above 30**
> after normalisation, against 15.27 raw (03).

Removing the between-member spread removes the thing that was propping up the
denominator, so collapse gets easier.

**Falsified if** normalised-5 comes in at or below raw-5's 15.27.

## P3 — the max is a scale collapse, not a large deviation

The mechanism test, and the one that decides between "small groups are noisy"
and "the scale estimator fails at small n". At the instant of maximum abs z,
record the scale and compare it to that group's own median scale:

> `scale(argmax) / median(scale)` is **below 0.3** for 5-member groups and
> **above 0.6** for 12-member groups.

**Falsified if** 5-member groups come back above 0.6 — that would mean the max
is driven by a genuinely large deviation, and the count rule would be about
something else entirely.

## P4 — the property, stated numerically

If P3 holds, the rule can be written without reference to n at all. The
candidate property is the **scale collapse ratio**: the 5th percentile of the
per-instant scale over its median.

> Measured over the baseline: **above 0.5** at n = 12, **0.10 – 0.35** at n = 5,
> and **at or near 0** at n = 3.

A group qualifies for peer comparison when this ratio clears a floor, whatever
its size. That is the restatement the count is standing in for — but it is a
proposal until P3 and P4 both land, and `MIN_PEERS = 12` stays in force
meanwhile.

**Falsified if** the ratio does not order the group sizes, or if 5-member and
12-member groups overlap.

## P5 — the fixed service group is not stable across runs

06 measured `error_ratio`'s peer baseline at **51.82** on a scenario run. This
run measures it again on a different run.

> The two differ by **at least 2x** in one direction or the other, because a
> maximum over a heavy-tailed quantity is not a reproducible statistic.

**Falsified if** it comes back within 2x of 51.82 — which would be real evidence
that the fixed 5-service group has a stable baseline, and that a threshold above
it is writable. That is the outcome that would rescue the small groups, and it is
a live possibility rather than a strawman.

## P6 — normalisation barely moves the services

Internal control. The services are already at identical base levels, so
normalising should change almost nothing.

> Normalised `error_ratio` and `ci_ratio` peer baselines land within **20%** of
> their raw values.

**Falsified if** either moves by more than 20% — which would mean the
normalisation is doing something other than removing level differences, and P1
and P2 could not be read as I intend to read them.

---

## What each outcome licenses

| outcome | what it licenses |
|---|---|
| P3 and P4 hold | The rule becomes a property — scale stability — and small groups can qualify if they clear it. `MIN_PEERS` becomes a derived consequence, not an axiom. |
| P3 holds, P4 fails to order | Scale collapse is the mechanism but the proposed statistic does not capture it. Keep the count; keep looking for the statistic. |
| P3 fails | The mechanism is wrong. `MIN_PEERS = 12` stays an empirical count with no explanation, which is worse but honest. |
| P5 falsified | The 5-service groups have a stable baseline. Peer comparison becomes available for `error_ratio` and `ci_ratio` with a high threshold, and 06's 2-of-5 conclusion needs revising upward. |

No threshold is written from this run. The matrix follows it.

---

# Result — measured 2026-08-24

One baseline-only run at 630x for 480s, `kept_up=True`, `degraded=False`.
Window start and end recorded, which is why the quantile analysis below is a
re-query of the same window rather than a second run. Raw data in
`data/scale-stability.json` and `data/scale-quantiles.json`.

## Full groups, raw and normalised

| group | n | max abs z | scale@max / median | p05 / median | floor |
|---|---|---|---|---|---|
| `memory` raw | 12 | **3.95** | 0.874 | 0.872 | 0.0% |
| `memory` normalised | 12 | **13.28** | 0.184 | 0.490 | 0.0% |
| `cpu` raw | 12 | 3.56 | 0.322 | 0.452 | 0.0% |
| `cpu` normalised | 12 | 8.07 | 0.466 | 0.504 | 0.0% |
| `latency` raw | 12 | 5.56 | 0.430 | 0.567 | 0.0% |
| `latency` normalised | 12 | 9.60 | 0.254 | 0.517 | 0.0% |
| `error_ratio` raw | 5 | 25.73 | 0.068 | 0.200 | 0.0% |
| `ci_ratio` raw | 5 | 77.45 | 0.030 | 0.242 | 0.0% |
| `disk_ratio` raw | 3 | 0.00 | n/a | n/a | 100.0% |

## Seeded subsets, median over 40 draws

| metric | n | raw | normalised |
|---|---|---|---|
| `memory` | 3 | 4.30 | 52.03 |
| `memory` | 5 | 2.00 | 37.48 |
| `memory` | 8 | 3.80 | 16.44 |
| `cpu` | 5 | 11.85 | 50.87 |
| `latency` | 5 | 38.35 | 41.06 |
| `latency` | 8 | 8.25 | 13.23 |

---

## P1 — FALSIFIED

Normalised 12-member groups are worse than raw at every metric: `memory`
3.95 to **13.28**, `cpu` 3.56 to 8.07, `latency` 5.56 to 9.60. The bound was 10
and `memory` cleared it.

**Removing between-member level differences makes peer comparison worse, at
n = 12.** So this is not a pure count effect, and homogeneity is not the
condition peer comparison wants - it is the condition it suffers under.

## P2 — HIT

Normalised 5-member medians: `memory` **37.48**, `cpu` **50.87**, `latency`
**41.06**, all above the predicted 30, against raw medians of 2.00, 11.85 and
38.35 on the same subsets.

## P3 — FALSIFIED as stated, and right about the mechanism

The stated falsifier was "5-member groups above 0.6". `memory:5:raw` came back
at **0.813**, so P3 fails.

It failed by tying the collapse to group size instead of to the outcome. Tied to
the outcome it is close to deterministic - the rank correlation between
`scale@max / median` and `max abs z` is **-0.958** over the 28 groups in the
first table, and **-0.932** over 154 groups once the subsets are expanded.

Where the maximum is large the scale is collapsed at that instant
(`ci_ratio` 0.030 with 77.45; `error_ratio` 0.068 with 25.73). Where it is small
the scale is intact (`memory:8:raw` 0.901 with 3.80). The mechanism is
confirmed; the prediction attached it to the wrong variable.

## P4 — survived its falsifier and failed its purpose

The falsification condition was overlap between 5-member and 12-member groups.
There is none: 12-member p05/median spans 0.452 to 0.872, 5-member spans 0.200
to 0.261. Ordering holds, no overlap, condition not met.

**And the statistic does not work.** `memory:normalised` has p05/median 0.490
and a max abs z of 13.28; `cpu:raw` has 0.452 and 3.56. The proposed property
orders the group *sizes* while failing to separate the *outcomes*, which is the
thing it was proposed to do.

That is the third instance in two documents of a falsification condition passing
while the prediction it guards is wrong. Here the condition tested the ordering
by n - which was never in doubt - instead of the discrimination that mattered.
The lesson recorded after 07 was to ask what could satisfy a clause other than
the case it targets; the complement is to ask whether the clause can be
satisfied *by the very thing the prediction is trying to displace*. P4's
falsifier was satisfied by group size.

## P5 — HIT, on a knife edge

06 measured `error_ratio`'s peer baseline at 51.82. This run gives **25.73**, a
factor of **2.014** - over the stated 2x by a margin that would vanish on
rounding. It is scored a hit and should be read as "unstable, marginally
demonstrated", not as a clean result.

One thing strengthens it: this run has roughly 480 baseline instants against
06's 137, and a maximum over more instants can only grow. The larger sample
produced the smaller maximum.

## P6 — FALSIFIED, and it invalidates part of the reading

`error_ratio` moved 25.73 to 29.82 (+15.9%, inside the bound). `ci_ratio` moved
77.45 to **32.78**, a **-57.7%** change.

Identical base levels do not give identical realised medians. `ci_ratio` carries
the largest noise in the simulator (0.35 relative), the value is clipped at zero
in `_baseline`, and services have two or three pods - so the mean of a service's
pods has a different variance and a different clipping bias per service.
**Base-level homogeneity is not realised-level homogeneity.**

The pre-registered consequence was explicit: if P6 fails, "P1 and P2 could not be
read as I intend to read them". Honouring that, rather than arguing around it:

On inspection the effect is in the *service* groups, where realised medians
differ more than base levels imply. The pod normalisation divides each pod by its
own median, and pods differ in level by 5.8x to 7.6x, so it demonstrably removes
level differences there. That is a reasonable argument and it is exactly the
shape of a post-hoc rescue, which is what pre-registering the consequence was
meant to prevent. **P1 and P2 are therefore marked provisional**, and 09
re-tests the normalisation directly rather than accepting the argument.

---

## What the run establishes

**Exchangeability is backwards.** Peer comparison wants members that differ.
Between-member spread makes the MAD a stable divisor dominated by persistent
structure; homogeneity leaves it estimating noise, where it is jumpy and can
only fail downward - a small denominator inflates z, and no accident makes the
denominator large.

**The property beats the count, measured on the same 154 groups.**

| rule | accepts | of those, blew up | worst accepted | rejects that were fine |
|---|---|---|---|---|
| `min(scale)/median(scale) >= 0.259` | 35 | **0** | 6.89 | 7 |
| `n >= 12` | 6 | **3** | 13.28 | 39 |

Rank correlation with `max abs z`: the scale statistic **-0.932**, group size
**-0.476**.

Two rows settle the count question on their own. `memory:3:raw` - three members -
reaches **1.02**, the best-behaved group in the table. `memory:normalised` -
twelve members - reaches 13.28. **Twelve peers is neither necessary nor
sufficient.**

## The threshold is fitted, and is not adopted

0.259 was chosen after seeing these results, and it sits exactly at the maximum
of the failing class, which is the most overfit point available. Reporting it as
a validated rule would be the fitting behaviour this practice exists to stop.

`MIN_PEERS = 12` stays in force. 09 states what the fitted threshold should do
out of sample, before a fresh run is made, and predicts that this particular
value will fail.
