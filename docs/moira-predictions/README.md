# Moira predictions

Numbers written down **before** the measurement that decides them, so a miss
stays visible instead of becoming a parameter nobody questions. Same practice
as [`docs/argus-predictions/`](../argus-predictions/README.md), for the same
reason, and under the same guard - `tests/unit/test_prediction_records.py`
finds this directory by pattern.

| record | subject | result |
|---|---|---|
| [01-disk-time-to-full.md](01-disk-time-to-full.md) | The fill rate, fit quality and time-to-full Moira reports on `disk_pressure`; a clean disk on `memory_leak`; memory refused everywhere; one confidence step on `disk_exhaustion` | **5 hit, 1 miss** - the 90 % time-to-full landed at 20.5 h against 18.5 h predicted, tilted by the generator's seasonal term, which was the first item under "what would make me wrong" |

## Raw measurements

[`data/`](data/README.md) holds the JSON each scoring cites.
