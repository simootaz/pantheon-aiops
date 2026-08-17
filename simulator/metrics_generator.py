"""Synthesises Prometheus-shaped metrics for the fake cluster.

THE BASELINE IS THE WHOLE POINT
-------------------------------
A flat baseline would pass every structural test and make the simulator
worthless. An anomaly detector trained on a constant learns that any change is
an anomaly; trained on a constant plus noise it learns a threshold; trained on
something with **daily seasonality** it has to learn that 09:00 and 03:00 differ
legitimately — which is the actual problem in production.

So every series carries:

* a **diurnal cycle** — a night trough, a morning ramp, a midday peak, an
  evening decline. Not a plain sine: real traffic is asymmetric, rising faster
  than it falls, so the shape is a skewed cosine.
* a **weekly component** — weekends quieter than weekdays, so a detector cannot
  simply learn "24h" and stop.
* **gaussian noise**, scaled per metric. Latency is noisier than memory.
* **per-pod phase jitter**, so twelve pods are not twelve copies of one curve.

`tests/integration/test_simulator_data.py` asserts the seasonality is
statistically detectable rather than eyeballed.

COUNTERS READ `speed` TIMES FASTER THAN THEY "ARE"
--------------------------------------------------
Gauges are unaffected by compression: a CPU reading is the same number whatever
the clock does. Counters are not. Each push adds `rate * tick_seconds` of
*simulated* increments, and Prometheus scrapes in *wall* time, so a `rate()`
query returns roughly the simulated rate multiplied by the compression factor.

This is correct — the alternative, scaling increments by wall time, would mean a
three-hour fault delivered three seconds' worth of requests and the simulated
totals would be wrong — but it means **absolute** counter thresholds are
meaningless at speeds other than 1. Anything comparing windows within one run
(z-score, ratios, the tests in this repository) is unaffected, because the factor
is identical on both sides and cancels. Anything asserting "more than N errors
per second" must run at `speed=1` or work in ratios.

It is the same family of limitation as the pushgateway discarding timestamps,
and ROADMAP tracks both against `remote_write`.

DETERMINISM
-----------
The generator is seeded per pod and metric, so two runs of the same scenario
produce the same series. A scenario that behaves differently each run cannot be
ground truth.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import httpx
import numpy as np
from prometheus_client import CollectorRegistry, Counter, Gauge, push_to_gateway
from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest

from simulator.cluster import CLUSTER, NAMESPACE, NODES, NODES_BY_NAME, PODS, Node, Pod, pods_for
from simulator.scenario import Deviation, MetricName, Phase, Shape

SECONDS_PER_DAY = 86_400.0
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY

#: Relative gaussian noise per metric. Latency genuinely varies more than memory
#: does, and giving everything the same jitter is its own kind of flat line.
NOISE: dict[MetricName, float] = {
    MetricName.CPU: 0.06,
    MetricName.MEMORY: 0.015,
    MetricName.REQUEST_RATE: 0.08,
    MetricName.LATENCY: 0.18,
    MetricName.ERROR_RATE: 0.30,
    MetricName.DISK_USED: 0.004,
    # Restarts are events, not a level. A healthy pod restarts zero times, and
    # jittering that would invent restarts nothing caused.
    MetricName.RESTARTS: 0.0,
}

#: How strongly each metric follows the daily cycle. Memory barely does - a
#: process holds its heap overnight - while request rate is almost all cycle.
SEASONAL_AMPLITUDE: dict[MetricName, float] = {
    MetricName.CPU: 0.45,
    MetricName.MEMORY: 0.08,
    MetricName.REQUEST_RATE: 0.55,
    MetricName.LATENCY: 0.25,
    MetricName.ERROR_RATE: 0.20,
    MetricName.DISK_USED: 0.01,
    # Restarts have no daily rhythm: a crash loop does not wait for the morning.
    MetricName.RESTARTS: 0.0,
}


def require_every_metric(name: str, table: dict[MetricName, float]) -> None:
    """Refuse to import with a gap in a per-metric table.

    Both tables are read with `table[metric]`, never `table.get(metric, 0.0)`.
    A default would let a metric added later fall silently to no noise and no
    seasonality — a flat line, produced by exactly the accident this simulator
    exists to catch. Raising here turns that into an import error instead.

    `RESTARTS` was missing from both tables and from the baseline table when
    this was first written, and the generator died on its first push.
    """
    missing = set(MetricName) - set(table)
    if missing:
        raise RuntimeError(
            f"{name} has no entry for {sorted(metric.value for metric in missing)}. "
            "Every metric needs an explicit decision, including 'zero'."
        )


require_every_metric("NOISE", NOISE)
require_every_metric("SEASONAL_AMPLITUDE", SEASONAL_AMPLITUDE)


def _seed(*parts: str) -> int:
    """A stable seed from names, so runs reproduce without a global RNG."""
    return abs(hash("::".join(parts))) % (2**32)


def diurnal(day_fraction: float, phase_shift: float = 0.0) -> float:
    """A skewed daily curve in [-1, 1], peaking early afternoon.

    Real traffic rises faster than it falls, so this is not a plain cosine: the
    ascending half is compressed. A symmetric sine would let a detector learn
    the shape too easily and would look wrong to anyone who has watched a real
    dashboard.
    """
    position = (day_fraction + phase_shift) % 1.0
    # Skew: shift the peak to ~14:00 and steepen the morning ramp.
    skewed = position + 0.06 * math.sin(2 * math.pi * position)
    return -math.cos(2 * math.pi * (skewed - 0.06))


def weekly(simulated_seconds: float) -> float:
    """A weekly multiplier: weekdays busy, weekends quiet.

    Without this a detector that learns a 24h period explains everything, and
    the simulator stops being a useful adversary.
    """
    day_of_week = (simulated_seconds / SECONDS_PER_DAY) % 7.0
    weekend = 5.0 <= day_of_week < 7.0
    return 0.72 if weekend else 1.0


@dataclass(slots=True)
class PodState:
    """Mutable per-pod counters that must only ever increase."""

    requests_total: float = 0.0
    errors_total: float = 0.0
    restarts_total: float = 0.0
    disk_used_bytes: float = 0.0
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0))


class MetricsGenerator:
    """Produces one snapshot of every series, and pushes it to a pushgateway."""

    def __init__(self, gateway: str = "localhost:9091", job: str = "pantheon-sim") -> None:
        self.gateway = gateway
        self._gateway_url = gateway if "://" in gateway else f"http://{gateway}"
        self.job = job
        self._state: dict[str, PodState] = {
            pod.name: PodState(
                disk_used_bytes=0.34 * _node_for(pod).disk_bytes,
                rng=np.random.default_rng(_seed(pod.name, "metrics")),
            )
            for pod in PODS
        }

    # -- baseline ---------------------------------------------------------

    def _baseline(self, pod: Pod, metric: MetricName, simulated_seconds: float) -> float:
        """What this pod's metric would read with nothing wrong."""
        day_fraction = (simulated_seconds % SECONDS_PER_DAY) / SECONDS_PER_DAY
        # Each pod sits at a slightly different phase, so twelve pods are not
        # twelve copies of one curve.
        shift = (_seed(pod.name, metric.value) % 1000) / 1000.0 * 0.04
        season = diurnal(day_fraction, shift) * SEASONAL_AMPLITUDE[metric]
        week = weekly(simulated_seconds)

        base = {
            MetricName.CPU: pod.base_cpu_cores,
            MetricName.MEMORY: float(pod.base_memory_bytes),
            MetricName.REQUEST_RATE: pod.base_rps,
            MetricName.LATENCY: pod.base_latency_seconds,
            MetricName.ERROR_RATE: max(pod.base_rps * 0.004, 0.02),
            MetricName.DISK_USED: self._state[pod.name].disk_used_bytes,
            # A healthy pod restarts exactly zero times. This is why scenarios
            # perturb restarts with `offset` and never `factor`: a multiple of
            # zero is still zero, and the injection would silently do nothing.
            MetricName.RESTARTS: 0.0,
        }[metric]

        value = base * (1.0 + season) * week
        noise = self._state[pod.name].rng.normal(0.0, NOISE[metric] * abs(base))
        return max(value + noise, 0.0)

    # -- deviations -------------------------------------------------------

    @staticmethod
    def _shape_factor(shape: Shape, progress: float) -> float:
        """How far into a deviation we are, 0.0 to 1.0, by shape."""
        progress = min(max(progress, 0.0), 1.0)
        if shape is Shape.STEP:
            return 1.0
        if shape is Shape.RAMP:
            return progress
        if shape is Shape.SPIKE:
            # Fast on, slow off - what a retry storm actually looks like.
            return float(math.sin(math.pi * progress) ** 0.5)
        # Sawtooth: climbs and resets, e.g. a leak punctuated by OOM restarts.
        return (progress * 4.0) % 1.0

    def _apply(self, value: float, deviation: Deviation, shape_progress: float) -> float:
        strength = self._shape_factor(deviation.shape, shape_progress)
        if deviation.factor is not None:
            return value * (1.0 + (deviation.factor - 1.0) * strength)
        return value + (deviation.offset or 0.0) * strength

    def sample(
        self, pod: Pod, metric: MetricName, simulated_seconds: float, phases: list[Phase]
    ) -> float:
        """The value now: baseline, then any active deviation applied on top."""
        value = self._baseline(pod, metric, simulated_seconds)

        for phase in phases:
            if pod not in pods_for(phase.target):
                continue
            progress = (simulated_seconds - phase.start_seconds) / phase.duration_seconds
            for deviation in phase.deviations:
                if deviation.metric is metric:
                    value = self._apply(value, deviation, progress)
        return max(value, 0.0)

    # -- push -------------------------------------------------------------

    def push(
        self,
        simulated_seconds: float,
        phases: list[Phase],
        interval: float,
        client: httpx.Client | None = None,
    ) -> None:
        """Build a full snapshot and push it, replacing the previous one.

        `interval` is the simulated seconds since the last push, which is what
        turns a rate into a counter increment. Counters must only increase:
        pushing a decreased counter makes Prometheus infer a reset and produces
        a phantom spike in every `rate()` over that window.

        Pass `client` to reuse a connection. `push_to_gateway` opens a fresh TCP
        connection per call, and at one push per tick that handshake is a large
        share of what caps the achievable compression - measurably so. The
        library call stays as the fallback so this works standalone.
        """
        registry = CollectorRegistry()
        labels = ["pod", "node", "service", "namespace", "cluster"]

        cpu = Gauge("pantheon_pod_cpu_cores", "CPU cores in use", labels, registry=registry)
        memory = Gauge(
            "pantheon_pod_memory_working_set_bytes", "Working set", labels, registry=registry
        )
        latency = Gauge(
            "pantheon_http_request_duration_seconds",
            "Request duration, 95th percentile",
            labels,
            registry=registry,
        )
        requests = Counter(
            "pantheon_http_requests", "Requests served", [*labels, "status"], registry=registry
        )
        restarts = Counter(
            "pantheon_pod_container_restarts",
            "Container restarts",
            labels,
            registry=registry,
        )
        disk = Gauge(
            "pantheon_node_disk_used_bytes", "Disk used", ["node", "cluster"], registry=registry
        )

        for pod in PODS:
            state = self._state[pod.name]
            tags = [pod.name, pod.node, pod.service, NAMESPACE, CLUSTER]

            cpu.labels(*tags).set(self.sample(pod, MetricName.CPU, simulated_seconds, phases))
            memory.labels(*tags).set(self.sample(pod, MetricName.MEMORY, simulated_seconds, phases))
            latency.labels(*tags).set(
                self.sample(pod, MetricName.LATENCY, simulated_seconds, phases)
            )

            rps = self.sample(pod, MetricName.REQUEST_RATE, simulated_seconds, phases)
            errors_per_second = self.sample(pod, MetricName.ERROR_RATE, simulated_seconds, phases)
            state.requests_total += max(rps - errors_per_second, 0.0) * interval
            state.errors_total += errors_per_second * interval
            # The registry is rebuilt each push, so incrementing by the running
            # total sets the counter to it - without reaching into private state.
            requests.labels(*tags, "200").inc(state.requests_total)
            requests.labels(*tags, "500").inc(state.errors_total)

            restart_rate = self.sample(pod, MetricName.RESTARTS, simulated_seconds, phases)
            state.restarts_total += restart_rate * interval / SECONDS_PER_DAY
            restarts.labels(*tags).inc(state.restarts_total)

        for node in NODES:
            disk.labels(node.name, CLUSTER).set(self._node_disk(node, simulated_seconds, phases))

        if client is None:
            push_to_gateway(self.gateway, job=self.job, registry=registry)
            return
        # PUT, not POST: the snapshot replaces the group. POST would merge, and
        # a pod that stopped reporting would keep its last value forever.
        response = client.put(
            f"{self._gateway_url}/metrics/job/{self.job}",
            content=generate_latest(registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )
        response.raise_for_status()

    def _node_disk(self, node: Node, simulated_seconds: float, phases: list[Phase]) -> float:
        """Node disk, driven by whichever of its pods a phase is filling."""
        used = 0.34 * node.disk_bytes
        drift = 0.00004 * node.disk_bytes * (simulated_seconds / SECONDS_PER_DAY)
        used += drift

        for phase in phases:
            targets = pods_for(phase.target)
            if not any(pod.node == node.name for pod in targets):
                continue
            progress = (simulated_seconds - phase.start_seconds) / phase.duration_seconds
            for deviation in phase.deviations:
                if deviation.metric is MetricName.DISK_USED:
                    used = self._apply(used, deviation, progress)
        return min(used, float(node.disk_bytes))


def _node_for(pod: Pod) -> Node:
    return NODES_BY_NAME[pod.node]


# TODO: Phase 6 - emit via remote_write with explicit timestamps so a real
# multi-day baseline can be backfilled rather than compressed
