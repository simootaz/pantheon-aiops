# Argus calibration — predictions, written before each measurement

Each file states what a measurement was expected to produce, with numbers and
falsification conditions, **before it ran**. The point is not to be right. It is
that a miss stays visible: `11.10 measured where 3-8 was predicted` is a
recorded failure, where a number read afterwards would have been absorbed into
whatever story was already forming.

Two of these predictions were falsified outright, and one was falsified in its
specifics while its most important claim held. That is the intended yield.

## A correction about these files

They were **written** at the times stated in each file, in a session scratchpad
outside the repository. They were **committed** on 2026-08-21, all at once.

Commit messages during the work said "predictions committed first" and named a
hash. Those commits were real and their messages summarised the predictions -
but the files themselves were not in them, because the scratchpad is not
tracked. The claim was therefore weaker than it sounded: the reasoning was on
record in commit messages, the detailed tables were not on record anywhere
durable.

Recorded here rather than quietly fixed, because "the prediction was committed
before the run" is exactly the kind of process claim this repository has spent
the week checking rather than trusting - and it went unchecked for four
experiments.

| file | measurement | outcome |
|---|---|---|
| [01](01-window-cycle.md) | window as a fraction of the diurnal cycle | shape confirmed, 0.25 magnitude missed |
| [02](02-two-effects-and-peers.md) | drift vs estimator noise; peer-relative per scenario | both numeric predictions falsified |
| [03](03-grouping-and-group-size.md) | baseline anomaly, group size, grouping axis | P1 falsified, P2 falsified, P3 confirmed |
| [04](04-pushgateway-staleness.md) | DELETE semantics and Prometheus staleness | pending |
