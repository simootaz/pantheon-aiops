# Predictions, written BEFORE the measurement — 2026-08-27

Subject: two changes to `agents/log_clustering/templates.py`, both prompted by
what [01](01-template-recovery.md) measured.

1. `novel()` now tests whether an absence is **surprising** rather than
   treating any absence as a finding. A template at rate `p` in the incident
   should occur about `p × reference_lines` times in the reference; seeing none
   is only remarkable when that expectation was large. `SIGNIFICANCE = 0.05`.
2. `surged()` is new. Round 8 showed `bad_deploy_5xx` producing almost no novel
   templates, correctly: the simulator emits a 500 in normal traffic, so
   `request failed` is in every baseline window. A bad deploy does not introduce
   the pattern, it multiplies it, and novelty-by-absence is blind to that.

Stated plainly: the *form* of both tests is principled and 0.05 is conventional,
but the decision to add them came after seeing round 8's output. That is a
sharper risk of fitting than anything in record 01, which is why the falsifiers
below are aimed at the ways this could be flattering rather than right.

## Design

Identical to record 01's round 8 — two clean baselines and five scenarios
through the real simulator into a real Loki, read back through
`connectors/loki`, lines sorted into emission order, one shared field
classification via `compare()`. Only the two functions above changed.

## Prediction 1 — the low-count tail disappears

Round 8's novel counts were: `bad_deploy_5xx` 3, `memory_leak` 11,
`disk_pressure` 19, `flaky_test_storm` 3, `noisy_neighbor` 11 — dominated by
`request failed` variants at counts of one and two.

Predicted novel counts now: **0 – 4 per scenario**, and **every surviving novel
template has count ≥ 4**.

FALSIFIED IF: any scenario still reports more than 6, or any surviving template
has count ≤ 2. Either means the tail was not what I diagnosed it as.

## Prediction 2 — the real findings survive

The templates that matter kept high counts: `disk usage high` at 28,
`GC pause exceeded target` at 8, `cpu throttled` at 9.

Predicted: `disk_pressure` still reports `disk usage high`; `memory_leak` still
reports `GC pause exceeded target`; `noisy_neighbor` still reports
`cpu throttled`.

FALSIFIED IF: any of those three is filtered out. The rule would then be
removing signal along with noise, and 0.05 is the wrong level or the whole
framing is.

`GC pause exceeded target` at 8 lines is the one at risk — it is the closest to
the boundary of the three.

## Prediction 3 — false novelty on a clean window stays at zero

Round 8 measured 0 for `baseline_a`. Adding a filter cannot raise it.

Predicted: **0**.

FALSIFIED IF: anything other than 0. That would mean an implementation error
rather than a rule change, since a strictly narrower rule cannot admit more.

This one is deliberately unfalsifiable-by-the-rule and falsifiable-by-the-code.
It is a wiring check, not evidence about the method, and is marked as such
rather than counted as a hit that means something.

## Prediction 4 — `surged` finds what novelty could not

The claim that justifies the function existing.

Predicted: `bad_deploy_5xx` reports **≥ 1** surged template, and the top one by
ratio is a `request failed` variant.

FALSIFIED IF: zero surged templates for `bad_deploy_5xx`. The fault would then
be invisible to both halves, and Lethe cannot detect a bad deploy from logs at
all — which is a result worth having and would need saying out loud.

## Prediction 5 — `surged` is not indiscriminate

The control. A test that reports everything as surged proves nothing in P4.

Predicted surged count on the clean control (`baseline_a` against
`baseline_b`): **0 – 3**.

FALSIFIED IF: more than 8. Two clean windows differing in rates that often means
the Poisson model is wrong for this data — most likely because log volume
follows the diurnal curve, so two windows at different times of the simulated
day genuinely have different rates and every template looks surged.

I think this is the likeliest of the five to fail, and it is the one I would
most want to know about.

## Prediction 6 — scenario surges are stronger than baseline drift

If P5 shows a few surged templates on the clean control, the question becomes
whether the fault is distinguishable from that drift.

Predicted: the top surge ratio in each scenario exceeds the top surge ratio in
the clean control by at least **2x**.

FALSIFIED IF: the clean control's top ratio is within 2x of any scenario's. That
would make `surged` unusable without a rate model that accounts for seasonality
— which is the thing peer comparison gave Argus for free and logs do not have.

## Result — 2 hit, 3 falsified, 1 wiring check. `surged()` is deleted.

`data/09-surprise-and-surge.json`.

| # | predicted | measured | verdict |
|---|---|---|---|
| 1 | 0 – 4 novel per scenario, survivors count ≥ 4 | **0, 0, 0, 1, 0, 2**; survivors at 24, 9, 6 | hit |
| 2 | `disk usage high`, `GC pause`, `cpu throttled` all survive | disk ✓, throttled ✓, **GC pause gone** | falsified |
| 3 | 0 false novel on a clean window | 0 | wiring check — not evidence |
| 4 | `bad_deploy_5xx` surges, top is a `request failed` variant | 5 surges, top is `request completed status=204` | falsified |
| 5 | 0 – 3 surges on the clean control | **2** | hit |
| 6 | scenario top surge ≥ 2x the clean control's | control **1.289**, scenarios **1.311 – 1.541** | falsified |

## P6 is the one that decides it, and `surged()` has been removed

Two **clean** baseline windows reported surges at 1.289x. The five fault
scenarios topped out between 1.311x and 1.541x. A bad deploy was not
distinguishable from no fault at all — and every top surge in every run,
faulty or clean, was an ordinary `request completed` line.

The reason is the one Argus already paid for and wrote down. Log volume follows
the diurnal curve, so two windows taken at different points of the simulated day
have genuinely different rates. A Poisson tail assumes a constant rate, so it
calls that difference significant. **Comparing a window against an earlier
window measures the time of day.**

I predicted this was the likeliest of the five to fail and said it was the one I
most wanted to know about. It failed, and the honest response is to delete the
function rather than tune the level: no significance threshold fixes a test
whose null hypothesis is wrong. A working version needs the seasonality
cancelled, which means a **peer axis** — this pod's rate for this template
against its peers' rates for the same template at the same instant, the way
`agents/anomaly` does it. That is not done.

The consequence is stated in the code rather than left implied by an absence:
`bad_deploy_5xx` introduces no new template, it multiplies an existing one, and
**Lethe cannot detect it.**

## P4 failed twice over

Not only was the top surge not a `request failed` variant — nothing in the list
was. The five surges reported for `bad_deploy_5xx` are three of the same
`request completed` templates that surge in a clean baseline. P4 would have
been scored a hit on its first clause alone (`≥ 1 surged`), which is why it
carried a second one naming what the surge had to be.

## P2 was falsified because my reading of round 8 was wrong

`GC pause exceeded target` was one of the three templates I called signal. It is
emitted in **normal** operation — it is in every baseline window — so it cannot
be novel by absence at all.

What made it look novel in round 8 was the shared classification splitting it by
`heap_max_mb` (3000, 2937), a pod-specific constant. Those particular splits
happened to be missing from the reference. The finding I was protecting was an
artefact of a field split, and the surprise test removed it correctly.

So P2 is a genuine falsification of the prediction and a vindication of the
change. Worth separating: the prediction was wrong, not the code.

## What P1 and P5 establish

The low-count tail is gone. Nineteen novel templates for `disk_pressure` became
one, and it is `disk usage high` at 24 lines. `noisy_neighbor` reports
`cpu throttled` twice, split by hour, which is the known low-volume splitting
from record 01 and is still not fixed.

## A caveat on record 01's headline number

This run measured baseline Jaccard **0.80**, not the **1.00** of record 01's
round 8, with 74 templates against 61. Same code, same parameters, different
runs. A single measurement of stability is itself a sample, and 1.00 was the
better of two draws rather than the property. Neither record is entitled to
claim the template set is perfectly stable.
