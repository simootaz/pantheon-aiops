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

## Result — 5 hit, 1 miss, 0 falsified, after fixing the measurement subject

Eight rounds. `data/08-untruncated-novelty.json` is the scoring run; the seven
before it are committed too, because the path to it is the finding.

| # | predicted | measured | verdict |
|---|---|---|---|
| 1 | 25 – 70 templates on a clean baseline | **62** (both baselines) | hit |
| 2 | baseline Jaccard ≥ 0.90 | **1.00** — 62 of 62 shared | hit |
| 3 | 5 of 5 scenarios yield a novel template | **5 of 5** (3, 11, 19, 3, 11) | hit |
| 4 | 0 – 3 false novel on a clean window | **0** | hit |
| 5 | Jaccard ≥ 0.90 against the full set by N = 500 | **0.007** at 500, **1.00** at 1000 | miss |
| 6 | 1 – 3 stack-trace signatures | **1** | hit |

P5 is a real miss and the shape is the interesting part. Convergence is a
**step, not a ramp**: below `MIN_GROUP_FOR_VARIABILITY` every group is
shape-only, so its signatures are disjoint from the templated ones and Jaccard
sits near zero rather than climbing. It goes 0.007 → 1.00 between 500 and 1000
lines. The prediction assumed a curve; the mechanism has a threshold in it.

## What the first seven rounds established, which is most of the value

**Round 1.** 179 and 298 templates from ten source templates; baseline Jaccard
0.33; 60 false novel templates on a window with no fault in it. The cause was
visible in one rendered template: `ts=2026-08-27T13:54:17Z` was **inside** it.
A compressed run stamps thousands of lines with a handful of wall-clock seconds,
so the clock was low-cardinality and every cardinality rule called it a category.

Cardinality asks how many values a field has. It cannot ask whether they are a
*sequence*, and that is the question that separates a clock from a status code.

**Rounds 2–6 were me tuning a rule against one dataset, and that is worth
recording as its own failure.** Global sortedness caught nothing, because a
window read from Loki is several streams concatenated and the clock restarts at
every boundary. Counting adjacent pairs appeared to work — 62 templates,
Jaccard 0.984, zero false novelty — and **worked for the wrong reason**: ties
dominated the count, so any *rare* value read as ordered. `status` is 500 three
times in five thousand lines, so 99.9% of its pairs are equal and the single
most important discriminator in an incident would have been masked as a clock.
It would have passed every test on this data and failed on the first real one.

Excluding ties was correct and made things look worse, which is the honest
outcome: it revealed there were only three or four clock changes in a whole
simulated day to reason from.

**Round 7 stopped tuning and fixed the subject.** `simulator/log_generator.py`
stamped every line with `time.strftime(...)` at wall-clock time while ignoring
the `simulated_seconds` it was already being passed. Volume followed the
simulated day; the timestamp said three seconds had elapsed. That is the exact
contradiction the module's own docstring exists to forbid — *"a log stream that
is flat while its metrics are seasonal is a contradiction an agent would be
right to be confused by"* — and the timestamp was the same contradiction, unnoticed.

The measurement subject was unfit for the question being asked of it. No
parameter setting could have fixed that, and six rounds of trying is what it
cost to see it.

**Round 8 fixed a flaw I had introduced.** Truncating every run to a common
line count, to make the stability comparison fair, also truncated the scenario
runs — and the lines are in emission order, so keeping the first N keeps the
*earliest* N. It cut the fault period out of every scenario, reporting zero
novelty for `bad_deploy_5xx` and zero stack traces for `memory_leak`. Both read
as method failures. Both were the window never reaching the fault.

## What is now settled, and what is not

Settled: `_ordered` earns its place, the classification must be **shared**
between compared windows (`compare()`), and a window needs ~1000 lines before
its template set means anything.

Not settled, and stated rather than tuned away:

* **A tail of low-count false novelty remains.** Every scenario reports a few
  `request failed` variants at count 1–2 that are combinations the reference
  happened not to contain. The signal is legible beside them — `disk usage
  high` at 28, `GC pause exceeded target` at 8, `cpu throttled` at 9 — so
  novelty is reported **with counts** and nothing is filtered. A minimum-count
  threshold is available and is exactly the kind of number that would be tuned
  on this dataset, so it is not being set here.
* **Low-volume events still split by their variable fields.** `cpu throttled`
  appears twice, once per hour, because that group has too few lines for `ts`
  to accumulate `MIN_ORDER_CHANGES`. The rule needs evidence and a rare event
  does not provide it.
* **The Loki connector's 5000-line cap can hide a fault entirely.** Nothing
  here paged. A quiet incident in a noisy window is a case this has not tested.
