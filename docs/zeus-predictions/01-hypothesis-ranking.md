# Predictions, written BEFORE the measurement — 2026-08-31

Subject: `core/orchestrator/hypotheses.py`, which does not exist yet. It will
turn correlated Findings into ranked `RootCauseHypothesis` objects. This record
is written before a line of it, because the interesting question is not whether
it works — it is **how many of the five scenarios it can honestly name**, and
that number is very easy to inflate after the fact.

## What is already known, and therefore not being predicted

`agents/anomaly/agent.py` declares six signals: `memory`, `cpu`, `latency`,
`disk_ratio`, `ci_ratio`, `error_ratio`. `simulator/scenarios/*.yaml` declares
five ground-truth categories: `memory_leak`, `disk_exhaustion`, `flaky_test`,
`bad_deployment`, `resource_contention`.

Those are readable without running anything. The question is which of the five a
ranker can reach **from the signals alone**, without inventing a relationship
nothing measures.

## The distinction the design rests on

A signal that **names** a cause and a signal that is **a symptom of many** are
different things, and a ranker that treats them alike will name a category for
every incident — which is the same as naming none.

Three of the six name a cause, because the metric *is* the thing the category
describes:

| Signal | Category | Why this is semantics, not a heuristic |
| --- | --- | --- |
| `memory` | `memory_leak` | `pantheon_pod_memory_working_set_bytes` **is** resident memory. Sustained growth without release is what the phrase means. |
| `disk_ratio` | `disk_exhaustion` | The metric **is** used ÷ total. Approaching 1 is the definition. |
| `ci_ratio` | `flaky_test` | The metric **is** pipeline failure ratio. |

Three do not:

| Signal | Why it names nothing | What would be needed |
| --- | --- | --- |
| `error_ratio` | Errors rising says errors rose. It does not say a deploy caused it. | A deployment event. `connectors/gitlab` and `connectors/github` are Phase 4 stubs. |
| `cpu` | High CPU on one pod is not contention. Contention is a claim about **neighbours**. | Topology — which pods share a node. The Kubernetes connector is a Go stub. |
| `latency` | A symptom of nearly everything, including all five scenarios. | Nothing; it is corroborating by nature. |

So the design: a hypothesis is proposed **only** from a naming signal. A
corroborating signal can raise confidence in a hypothesis already proposed and
can never propose one alone. With only corroborating signals the answer is
`UNKNOWN`, which the vocabulary has specifically so that "we do not know" is
statable rather than absent.

## Prediction 1 — three of five scenarios get their category, two get `UNKNOWN`

`memory_leak`, `disk_pressure` and `flaky_test_storm` produce a leading
hypothesis matching ground truth. `bad_deploy_5xx` and `noisy_neighbor` produce
`UNKNOWN`.

I am predicting the two misses deliberately and in advance. A ranker that named
all five would be one I had fitted to the answer sheet, and the honest report is
that **Zeus cannot conclude `bad_deployment` because nothing in this system
reports deployments.**

Confidence: high on the three hits — the signal is the definition. Lower on the
two `UNKNOWN`s only because `latency` fires in those scenarios too, and a
mistake in the corroborating rule would let it name something.

## Prediction 2 — a clean baseline produces no hypothesis at all, not `UNKNOWN`

An empty list. `UNKNOWN` means "something happened and we cannot explain it";
a clean window means nothing happened. Reporting `UNKNOWN` on a quiet system
would put an unexplained incident on every dashboard every five minutes.

## Prediction 3 — `bad_deploy_5xx` produces at least one Finding and still ranks `UNKNOWN`

This is the falsifier for Prediction 1's second half. If the scenario produced
no Findings, `UNKNOWN` would be right for the wrong reason — an empty input
rather than an unnameable one — and Prediction 1 would be untested.

I expect `error_ratio` and `latency` to fire, Lethe to be blind to it (recorded
in `agents/log_clustering/agent.py`: the scenario introduces no novel template),
and the ranking to be `UNKNOWN` **with both Findings attached as supporting
evidence**. An `UNKNOWN` that carries the evidence is a lead; one that carries
nothing is a shrug.

## Prediction 4 — confidence never reaches 1.0, and never exceeds the evidence

A hypothesis supported by one signal scores below one supported by two
independent ones. No hypothesis reaches 1.0, because 1.0 is a claim that no
further evidence could change the answer, and nothing here has tested a
hypothesis against a counterfactual.

I predict the memory-leak hypothesis lands in the 0.5–0.8 band with one agent
reporting, and higher only if Lethe independently corroborates.

## Prediction 5 — the ranking is order-independent

Shuffling the input Findings produces the same ranking. Stated because it is
the failure that hides: a ranker keyed on iteration order passes every fixture
written in one order and reorders itself in production, where Findings arrive
by whichever agent finished first.

## Design of the measurement

Unit-level first, against constructed Findings — Predictions 2, 4 and 5 are
fully decidable there and need no stack.

Predictions 1 and 3 need the simulator: one run per scenario through a live
stack, Zeus dispatching for real, the resulting Investigation's hypotheses
compared against the scenario's `expected_root_cause`. That is `make test-sim`
territory and is **pending** until it is run.

## Result — PENDING

Predictions 1 and 3 stay pending until the scenario measurement runs against a
live stack. Scoring them from constructed fixtures would be scoring the fixture:
I wrote the fixtures, so of course the ranker names what I put in them.

Predictions 2, 4 and 5 are decidable without a stack and are scored here, from
`tests/unit/test_hypothesis_ranking.py`.

**Prediction 2 — hit.** A clean window returns `[]`, and so does a window
holding only DEGRADED Findings. Guarded in both directions: a plant making a
degraded-only run report `UNKNOWN` fails
`test_a_window_of_only_degraded_findings_produces_nothing`.

**Prediction 4 — hit, with the band as predicted.** One naming signal scores
`BASE_CONFIDENCE = 0.55`; independent corroboration steps it up by 0.1 and it
caps at `MAX_CONFIDENCE = 0.9`. Nothing reaches 1.0. The same observation
reported twice does not raise it, and corroboration about a different subject
does not either — that second one matters more than it looks, because without
it a ranker becomes more certain the busier the cluster is.

**Prediction 5 — hit.** Eight seeded shuffles produce the same ranking. The
tie-break is the category name rather than insertion order, because insertion
order is agent completion order, which is a race.

One thing the predictions did not anticipate, found while wiring the aggregator:
a **tie has no leader**. Two hypotheses at equal confidence is exactly where
picking one would be the ranker inventing a judgement nothing made, so `leading`
returns `None` and `Verdict.confidence` stays 0.0. Prediction 4 said confidence
never exceeds the evidence; this is the same principle applied to the ranking
rather than to one hypothesis, and it was not written down in advance.
