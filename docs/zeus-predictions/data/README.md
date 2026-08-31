# Zeus measurement data

Empty, and correctly so. Every record in this directory is still **pending**:
the predictions are committed before the measurement that decides them, which is
the entire point of the practice.

`tests/unit/test_prediction_records.py::test_the_cited_measurements_exist` ties
the requirement to a **scoring** rather than to the directory existing, so a
directory whose records are all pending is allowed to hold no data - and the
moment one record is scored, its data has to be here and cited by name.

Predictions 2, 4 and 5 of
[`01-hypothesis-ranking.md`](../01-hypothesis-ranking.md) are decidable at unit
level and are scored from the test suite rather than from a JSON capture.
Predictions 1 and 3 need a scenario run against a live stack, and that run's
output belongs here.
