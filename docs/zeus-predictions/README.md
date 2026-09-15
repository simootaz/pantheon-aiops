# Zeus predictions

Numbers written down **before** the measurement that decides them, so a miss
stays visible instead of becoming a parameter nobody questions.

Same practice as [`docs/argus-predictions/`](../argus-predictions/README.md) and
[`docs/lethe-predictions/`](../lethe-predictions/README.md), and the same
reason: a rule chosen after looking at the answers is a description of those
answers.

Ranking has a particular version of that risk. There are five scenarios with
declared ground truth, and it is trivially easy to write a mapping that gets all
five and has learned nothing — the answer sheet is in the repository. So the
prediction here is not "does it work" but **how many of the five it can honestly
name**, committed before the code existed.

`tests/unit/test_prediction_records.py` enforces the shape — every record
tracked by git, every record carrying a scoring or saying plainly that it is
pending, and the index and the directory agreeing in both directions.

| record | subject | result |
|---|---|---|
| [01-hypothesis-ranking.md](01-hypothesis-ranking.md) | Which root causes a ranker can name from the signals that exist, and which it must refuse to name | 3 hit, 0 miss — 1 and 3 still **pending** a scenario run against a live stack |
