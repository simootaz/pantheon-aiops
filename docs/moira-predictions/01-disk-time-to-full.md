# Predictions, written BEFORE the measurement — 2026-09-14

Subject: `agents/capacity/` — Moira, which does not exist yet. It will fit a
trend to a resource that has a limit and say when the trend crosses it. This
record is written before a line of it, for the reason every file in
`docs/*-predictions/` exists: a number is very easy to explain after it has
been seen.

## What is already known, and therefore not being predicted

`simulator/scenarios/disk_pressure.yaml` says in its own header that it is
*"Moira's case rather than Argus's - the interesting question is not 'is
something wrong now' but 'when does this cross the line'"*. Its `disk_fills`
phase ramps `disk_used` on `node-a` by a factor of 2.6 over 216 000 s, and the
`eviction_threshold` phase begins at 194 400 s — 90 % of the way up.

`simulator/cluster.py` gives node-a 200 GiB. `metrics_generator._node_disk`
initialises usage at 0.34 of capacity, adds 0.4 % gaussian noise and a 1 %
seasonal term, and clips at the total. All of that is readable without running
anything, and the generator is deterministic, so the values below were computed
from it directly:

| Ramp progress | Simulated time | `disk_ratio` on node-a |
| --- | --- | --- |
| 0.00 | 172 800 s | 0.3362 |
| 0.50 | 280 800 s | 0.6122 |
| 0.90 | 367 200 s | 0.8304 |
| 1.00 | 388 800 s | 0.3435 — the phase has ended and the deviation is gone |

That last row matters: the simulator's deviations are not persistent, so the
window Moira reads has to be *inside* the fill. That is also true of a real
incident, so it is not a test convenience.

## The distinction the design rests on

A projection is two numbers and a statement about whether they can be trusted:
a **rate**, a **time to limit**, and a **fit quality**. The first two are
definitional — a least-squares slope is what "rate" means, and
`(limit − current) / rate` is what "time to limit" means. The third is where a
forecaster gets to lie, so it is reported rather than thresholded away: a
window whose fit is poor produces a Finding with a poor fit on it, not a
suppressed Finding and not a confident one.

Two things are refused outright, and reported as refusals:

- **A resource with no limit metric.** `pantheon_pod_memory_working_set_bytes`
  has no `_limit_bytes` beside it in the simulator, and the Kubernetes connector
  that would read a container's limit is a Go stub. Moira cannot say when
  memory crosses a line it cannot see, and inventing a line — the node's total,
  say — would be projecting against a number that means something else.
- **A trend that is not a trend.** A resource whose window has a negative or
  near-zero slope is not filling. Reporting a time-to-limit of "never" is the
  same as reporting a clean window, and Argus's rule applies: a clean window is
  a result, not a finding.

## Prediction 1 — the fill rate on node-a is 0.0092 ± 0.001 per hour

Read from the table: (0.8304 − 0.3362) / 54 h. The noise is 0.4 %, so a
least-squares slope over any window longer than an hour or two should land
within 10 % of it. A miss here means the fit is reading something other than
the ramp — most likely the seasonal term, which the generator applies to disk
even though disk has no daily rhythm of its own.

Confidence: high. This is arithmetic on a deterministic generator.

## Prediction 2 — R² above 0.99 over the fill

A straight ramp with 0.4 % noise is about as linear as data gets. If R² lands
below 0.95 the seasonal term is larger in the data than the tables suggest, and
that is worth knowing about the generator, not about Moira.

Confidence: high.

## Prediction 3 — time to full from the midpoint is 42 h, and from 90 % is 18.5 h

`(1 − 0.6122) / 0.00915 = 42.4 h` and `(1 − 0.8304) / 0.00915 = 18.5 h`.

The second number is the one the scenario is about: eviction begins at
90 %, and a forecast that said "18 hours to full" at that moment is late by
exactly the gap between full and the eviction threshold. Moira projects to
**full**, because full is the only limit the metric defines; the kubelet's
threshold is a configuration value it cannot read yet. The docstring will say
so rather than substituting a default.

Confidence: high on the arithmetic, and it is the arithmetic being predicted.

## Prediction 4 — on `memory_leak`, disk produces nothing

The only disk movement is the 0.00004-per-day accumulation, which is a
time-to-full of several years. Moira's horizon is 72 h — three days, the
scenario's own framing of "slow burn" — so this is a clean window for disk.

This is the control. A forecaster that raised a capacity Finding on every
scenario would be reporting the accumulation term, and the accumulation term is
the generator's, not the cluster's.

Confidence: high.

## Prediction 5 — memory is DEGRADED on every scenario, including `memory_leak`

Stated as a miss, in advance. `memory_leak` is the scenario a capacity
forecaster most obviously ought to catch, and Moira will not, because nothing
tells it the limit. Argus already catches the growth as an anomaly and
`hypotheses.py` already names the leak from the metric's semantics; what is
missing is the number "and at this rate it OOMs in N hours", and that number
needs a limit.

When `kubernetes.top` exists this refusal becomes a projection without the
forecaster changing — the same way the plan widened when Lethe landed without
the planner changing.

Confidence: certain, because it is a statement about which metrics exist.

## Prediction 6 — with Moira in the plan, `disk_exhaustion` confidence rises by one step

`hypotheses.py` counts independent observations as `(agent, metric)` pairs and
adds `CORROBORATION_STEP = 0.1` per additional one. Moira's Finding carries no
`METRIC_WINDOW` evidence — it carries a forecast — so `_signal_of` returns
`None` and it is **corroborating**, which is the safe default for an evidence
kind the ranker does not recognise. It attaches to the `disk_exhaustion`
hypothesis only if it shares a subject with Argus's disk Finding, and both are
about `node/node-a`.

So on `disk_pressure` the leading confidence should move from *n* × 0.1 + 0.55
to (*n* + 1) × 0.1 + 0.55, where *n* is whatever it is today — 0.55 if Argus's
disk Finding stands alone, 0.65 if Lethe's `disk_warning` cluster already shares
the subject. I do not know *n* without running it, and I am predicting the
**step**, not the level.

Confidence: medium. The mechanism is readable; whether Lethe's log Finding
carries `node-a` as its subject is not something I have checked, and I am
deliberately not checking it before writing this down.

## What would make me wrong

- A slope pulled off by the seasonal term (P1, P2).
- Lethe's cluster subject matching in a way that makes the step land on a
  different hypothesis (P6).
- The generator clipping at the total in a way that flattens the top of the
  ramp inside the window (P1).

## What is not being claimed

That Moira predicts eviction. It predicts full. That Moira handles memory. It
refuses, and says why. That 72 h is anything but a parameter — it is the
scenario's own timescale, and it is on the Finding so a reader can disagree
with it.

## Addendum, written while building the agent and still before any measurement

Two things I did not see until the code was in front of me. Recorded here
rather than folded into the predictions above, so the record shows what was
known when.

**Compression does not cancel for a rate.** Argus's z-scores are ratios and the
simulator's speed factor divides out. A slope does not: at 500×, Prometheus
sees the 60-hour ramp go by in 7.2 wall minutes, and Moira - which reads wall
time - will report a rate of roughly 0.0092 × 500 ≈ 4.6 per hour and a
time-to-full of 42 h / 500 ≈ 5 minutes. So P1 and P3 are predictions about the
generator's **simulated** series, which is what the offline test in
`agents/capacity/tests/` fits directly. Under `make test-sim` the same
predictions hold after dividing by the speed, and the integration assertion
will be written that way. A Moira that reported simulated hours under
compression would be one that knew it was being simulated.

**The incident window is the wrong window for a trend.** The router hands every
agent a five-minute lookback, which is right for "what just moved" and useless
for a fill measured in days - five minutes of a 60-hour ramp moves the ratio by
0.0008 against 0.002 of noise, and the fit would report the noise. Moira reads
its own 24-hour window ending at the incident's end and puts *that* window on
the Finding. This changes no prediction; it changes what a prediction about a
five-minute window would have said, which is "R² near zero", and is the reason
none of the above was written about one.
