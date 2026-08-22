# Predictions 5 — run ordering, written BEFORE the measurement

**Date written:** 2026-08-22, before any run.

## What changed since this test was first specified

The mechanism it was designed to probe is now understood, and it is not the one
we suspected.

- **Carry-forward is dead.** After a *real* delete, Prometheus emits staleness
  within 2 seconds. There is no five-minute lookback filling the gap.
- **The reset never worked.** Every reset deleted `pantheon_sim`; the generator
  pushes to `pantheon-sim`; the gateway answers 202 either way. So during every
  settle the previous run's final values continued to be served and scraped.

So the question is now narrower and better posed: **with a reset that actually
clears, does running a scenario after another still change its baseline?**

## The measurement

`noisy_neighbor`, peer-relative latency across all 12 pods, baseline max |z|,
under three conditions. Everything else held: same speed, same duration, same
wall-paced runner, same fixed peer set, `reset()` with its postcondition
throughout.

| condition | description |
|---|---|
| **S** standalone | reset, settle, run `noisy_neighbor` |
| **A** after a fault | run `bad_deploy_5xx`, reset, settle, run `noisy_neighbor` |
| **N** no reset | run `bad_deploy_5xx`, settle only, run `noisy_neighbor` |

**N** reproduces the old broken behaviour deliberately, so the comparison is
against a measured control rather than against a memory of an earlier run.

## Predictions

Anchors: 5.04 measured standalone with a broken reset; 22.76 measured twice
sequentially with a broken reset.

| condition | predicted baseline max \|z\| |
|---|---|
| **S** standalone | **4 - 7** |
| **A** after a fault, reset works | **4 - 8** |
| **N** after a fault, no reset | **15 - 30** |

**Predicted: order does NOT matter once the reset works.** S and A land within a
few units of each other; N reproduces the anomaly.

FALSIFIED IF A exceeds 12 while S stays under 8 - that is order mattering
through some mechanism other than retained series, and it would need its own
investigation.

ALSO FALSIFIED IF N comes in under 10, which would mean the broken reset is not
the cause either and 22.76 has a fourth explanation nobody has proposed.

## Calibration note on these predictions

Three of my last predictions missed in the same direction: I over-predict spread
between conditions and under-predict the middle. If that bias holds, S and A
will be closer together than I have written, and N lower than 15.

## The two outcomes, with what each costs

**Order still matters with a working reset** (A high, S low). The cause is not
retained series. That is a new finding and needs its own investigation before
any Experiment B number is trusted - and before the peer-relative design is
written up, since every scenario in `peer2.txt` after the first ran sequentially.

**Order no longer matters** (S ≈ A, N high). This is the likely outcome and the
more expensive one. It means 22.76 was the broken reset, the four sequential
baselines in `peer2.txt` were measured under contamination that no longer
exists, and **Experiment B re-runs** - five scenarios, roughly 45 minutes.

Stated now so the re-run is a prepared cost rather than a conclusion to argue
against once the number is in front of me.

## Design for that re-run, if it happens

Isolation built in, not delegated to a settle that has already failed once:

- `reset()` before each scenario, with its postcondition asserted - a 202 is
  not evidence, and that is exactly how this was missed.
- The baseline window's start timestamp **recorded on the result**, so
  contamination is checkable after the fact rather than assumed absent.
- The first samples of each window checked against the previous scenario's final
  values, so overlap is measured rather than argued.

---

# Result — measured 2026-08-22

| condition | predicted | measured | |
|---|---|---|---|
| **S** standalone | 4 - 7 | **7.06** | miss, just above the range |
| **A** after a fault, reset works | 4 - 8 | **6.50** | hit |
| **N** after a fault, no reset | 15 - 30 | **22.76** | hit |

**Order does not matter once the reset works.** S and A differ by 0.56, well
inside noise, exactly as the calibration note anticipated - "S and A will be
closer together than I have written".

**N reproduced 22.76 to two decimal places** - the identical figure both earlier
peer runs produced. A control that reproduces the historical number on demand is
not a story that fits the data; it is the defect, recreated deliberately.

## What resolved it

Not a better hypothesis. Three had already failed - signal aliasing, partial
common-mode, coverage gaps - and each shared a flaw: it explained an anomaly
using data collected under conditions that no longer existed.

The fourth attempt **recreated the suspected broken condition alongside a working
one, in the same run.** That is the transferable part.

## Cost, as predicted

The likely-and-expensive outcome: four of five baselines in the previous
Experiment B were measured under contamination that no longer exists. Experiment
B re-ran - see `06-experiment-b-rerun.md`.
