# Raw measurements

The JSON each scoring in this directory cites. `tests/unit/test_prediction_records.py`
fails the build on a scoring whose data nobody can open.

**All eight rounds are here, including the six that were wrong.** Keeping only
the run that produced the committed parameters would leave a record saying the
method worked first time, which is the opposite of what happened - and the six
failures are where the reasoning is.

| file | what changed | outcome |
|---|---|---|
| `01-template-recovery.json` | the method as first written | 179 / 298 templates, Jaccard 0.33, 60 false novel on a clean window. `ts` was inside the template. |
| `02-template-recovery-ordered.json` | global sortedness as the clock rule | no change - a Loki window is streams concatenated, so the clock restarts at every boundary |
| `03-adjacent-pair-ordering.json` | fraction of adjacent pairs | 62 templates, Jaccard 0.984, 0 false novel. **Right answer, wrong reason** - ties dominated, so a rare value read as ordered |
| `04-shared-classification.json` | one classification shared between compared windows | correct change; the clock rule then regressed on a run whose window held three distinct stamps |
| `05-ties-excluded.json` | count only pairs where the value changes | worse, and honestly so: three or four clock changes in a simulated day is nothing to reason from |
| `06-emission-order.json` | sort the corpus by Loki's own nanosecond stamps | still nothing - the `ts` FIELD was wall-clock and unrelated to Loki's stamp |
| `07-simulated-timestamps.json` | **fixed the simulator**: log stamps follow simulated time | 62 templates, Jaccard **1.00** |
| `08-untruncated-novelty.json` | stopped truncating scenario runs to a common N | the scoring run. Truncation had been cutting the fault period out of every scenario |

Produced by a script under the session scratchpad, not committed: it drives
`simulator.runner` and reads back through `connectors/loki`, so it needs the
live stack and reproduces from `make up` plus the parameters recorded in each
file's `parameters` block.
