# Moira measurement data

The numbers each scoring cites, as produced.

| file | produced by | cited in |
|---|---|---|
| `disk-fit-offline.json` | `agents/capacity/forecast.fit` over `simulator.metrics_generator` directly, at 600 s cadence, in **simulated** time - the same series the unit tests fit | [01](../01-disk-time-to-full.md) |

Offline rather than through Prometheus: the generator is deterministic and the
predictions are about its series. The Prometheus-backed gate (`make test-sim`)
sees the same rates multiplied by the compression factor and the same hours
divided by it, and its capture belongs here beside this one when it has run.
