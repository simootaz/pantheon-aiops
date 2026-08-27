# Predictions, written BEFORE the measurement — 2026-08-27

Subject: `agents/log_clustering/templates.py` at
`MAX_STABLE_VALUES = 8`, `VARIABILITY_RATIO = 0.30`,
`MIN_GROUP_FOR_VARIABILITY = 12`. Those three numbers are guesses. This
measurement is what decides them.

## What is already known, and therefore not being predicted

`simulator/log_generator.py` defines **ten** named templates: `request`,
`request_error`, `gc_pause`, `pool_warning`, `pool_exhausted`, `stack_trace`,
`oom_killed`, `disk_warning`, `throttled`, `test_flake`. Their placeholder
fields are visible in that file, as are the value sets `PATHS` (5), `METHODS`
(3), `SUITES` (3) and `TESTS` (3).

So "does the clusterer find ten templates" is not the question — the answer is
readable without running anything. The question is what a **corpus-driven**
variability rule does when it has never been told any of that, and whether the
result is stable enough for novelty detection to mean something.

Every prediction below is about a number I have not looked at.

## Design

Two independent clean baseline runs (A, B) and one run per scenario, all
through the real simulator into a real Loki, read back through
`connectors/loki`. Lines are taken from the whole run window. The clusterer is
run offline on the returned lines; nothing here depends on Lethe existing yet.

## Prediction 1 — the method produces MORE templates than the source has

Low-cardinality fields survive the variability rule and multiply. `method` (3)
and `path` (5) are both under `MAX_STABLE_VALUES = 8`, so `request` alone should
split into up to 15, times however many distinct `status` values it emits.

Predicted distinct templates on a clean baseline window: **25 – 70**.

FALSIFIED IF: the count is ≤ 12 (the multiplication did not happen, meaning the
ratio rule is suppressing discriminators the cap allows), or ≥ 200 (a field that
should be variable is being kept, and the templates are identifiers).

## Prediction 2 — the split is stable across independent runs

The multiplication in P1 is only acceptable if the SAME combinations appear
every time. If run A yields 40 templates and run B yields 40 different ones,
every incident window is trivially "novel" and `detect_novel_pattern` is noise.

Predicted Jaccard between the baseline template sets of runs A and B:
**≥ 0.90**.

FALSIFIED IF: < 0.75. That kills `MAX_STABLE_VALUES = 8` outright and the fix is
a much lower cap — a field with 5 values is then an identifier for this purpose,
not a category.

I expect this one to be the closest. Rare combinations — `PUT /healthz` with a
non-200 status — may appear in one run and not the other, and each miss costs
Jaccard directly.

## Prediction 3 — every scenario introduces a template absent from baseline

The one that decides whether `detect_novel_pattern` is possible at all.

| scenario | expected novel template |
|---|---|
| `bad_deploy_5xx` | `request_error` |
| `memory_leak` | `oom_killed`, `stack_trace` |
| `disk_pressure` | `disk_warning` |
| `flaky_test_storm` | `test_flake` |
| `noisy_neighbor` | `throttled` |

Predicted: **5 of 5** scenarios yield at least one novel template.

FALSIFIED IF: any scenario yields zero. The live possibility is that the
baseline run already contains the "incident" template at low volume — the
generator emits `gc_pause` and `pool_warning` in normal operation, and if it
also emits a stray `stack_trace`, `memory_leak` has nothing new to show.

## Prediction 4 — false novelty is the failure mode, not missed novelty

Running `novel(A, B)` on two CLEAN baselines should be near-empty. Anything it
returns is a false positive by construction, since neither window had a fault.

Predicted false novel templates, baseline A against baseline B: **0 – 3**.

FALSIFIED IF: > 10. That means the template set is not a set — it is a sample —
and novelty against a single reference window cannot work at any parameter
setting. The fix would be a reference built from several runs, not a tuned
threshold.

## Prediction 5 — how many lines before the template set settles

Predicted: the template set from the first N lines reaches Jaccard ≥ 0.90
against the full-window set by **N = 500**, and ≥ 0.95 by N = 2000.

FALSIFIED IF: still below 0.90 at N = 5000. That would mean `MAX_LIMIT = 5000`
in the Loki connector is too small to template a window at all, and Lethe needs
paging before it needs anything else.

## Prediction 6 — stack traces group to one signature per fault

`simulator/log_generator.py` renders `stack_trace` with `{line}` and `{line2}`
varying per emission. `stack_traces()` masks digits before grouping, so all of
them should collapse.

Predicted distinct stack-trace signatures during `memory_leak`: **1 – 3**.

FALSIFIED IF: the count scales with the number of trace lines, i.e. > 20. That
means digit masking is not reaching the frames and the grouping is per-line.

## Result — PENDING

Not yet measured. The runs need the live stack exclusively, and the numbers
above are committed first so a miss stays visible.
