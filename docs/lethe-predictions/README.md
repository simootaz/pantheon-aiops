# Lethe predictions

Numbers written down **before** the measurement that decides them, so a miss
stays visible instead of becoming a parameter nobody questions.

Same practice as [`docs/argus-predictions/`](../argus-predictions/README.md),
and the same reason: a threshold chosen after looking at the data is a
description of that data. The interesting question is always whether it
survives data it was not derived from.

`tests/unit/test_prediction_records.py` enforces the shape — every record
tracked by git, every record carrying a scoring or saying plainly that it is
pending, the index and the directory agreeing in both directions, and every
cited measurement present in `data/`. It finds these directories by pattern
rather than by name, so this one was under guard the moment it existed.

| record | subject | result |
|---|---|---|
| [01-template-recovery.md](01-template-recovery.md) | Whether corpus-driven variability recovers a usable template set, and whether it is stable enough for novelty detection | 5 hit, 1 miss, 0 falsified — after six rounds of tuning that fixed nothing and one that fixed the simulator |

## Raw measurements

[`data/`](data/README.md) holds the JSON each scoring cites. Committed rather
than left in a session scratchpad, because a scoring that cites data nobody can
open is an assertion.
