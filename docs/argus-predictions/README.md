# Argus calibration — predictions, written before each measurement

Each file states what a measurement was expected to produce, with numbers and
falsification conditions, **before it ran**. The point is not to be right. It is
that a miss stays visible: `11.10 measured where 3-8 was predicted` is a
recorded failure, where a number read afterwards would have been absorbed into
whatever story was already forming.

Several of these predictions were falsified outright, and others were falsified
in their specifics while their most important claim held. That is the intended
yield.

Each file carries its **result** below the predictions, so a prediction and its
scoring live together. A prediction without its committed scoring is half a
record.

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
| [04](04-pushgateway-staleness.md) | DELETE semantics and Prometheus staleness | Q1 falsified — the delete never worked; Q2 and Q3 confirmed |
| [05](05-run-ordering.md) | does run order affect a baseline once the reset works | S/A confirmed, N reproduced 22.76 exactly |
| [06](06-experiment-b-rerun.md) | Experiment B re-run under asserted isolation | 4 of 5 separate, but only **2 of 5** have the 12 peers the rule requires; `carried=0` throughout |
| [07](07-aggregation-level.md) | Is the split per aggregation level, or per peer availability? | peer **availability**, not metric character; 4 hits, 3 misses |
| [08](08-peer-scale-stability.md) | Is MIN_PEERS a count, or a scale-stability property? | a **property** - scale stability beats size, -0.932 against -0.476 |
| [09](09-threshold-validation.md) | Does the fitted 0.259 threshold survive a fresh run? | no - **MIN_PEERS = 12 stays**; the property replicates, no safe threshold |
| [10](10-peer-bound-over-runs.md) | Is the peer bound uncalibratable, or was the wrong summary bounded? | **under-sampled** - one run was not enough; T=10 holds pod metrics at 1e-3 |
| [11](11-min-peers-decision.md) | Does a pooled bound over N runs make a 5-peer group safe? | yes at 1e-4 - **MIN_PEERS = 12 is replaced** by N >= 4 runs |
| [12](12-disk-fault-remeasure.md) | What is disk_ratio's peer fault z, now the gauge is real? | 1580.53 - **detectable at 131.7x**; my estimate was 10x low |
| [13](13-floor-validation.md) | Does the scale floor survive out-of-sample, and is `memory` a threshold at all? | floor holds to **4.4%**; `memory` is a topology constant, now guarded |
