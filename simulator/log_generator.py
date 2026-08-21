"""Synthesises structured logs for the same pods the metrics describe.

Logs and metrics must agree. A log stream naming pods the metric stream has
never heard of teaches an agent to correlate things that do not correlate, so
both read from `simulator.cluster`.

Templates are realistic in shape rather than exhaustive in variety: a request
log, a GC pause, a connection-pool warning and a stack trace cover the four
things an operator actually reads during an incident. Each carries the
placeholders a real line would, because a log clusterer that only ever sees
fixed strings learns nothing about masking variables.

Volume follows the same diurnal curve as the metrics — a log stream that is
flat while its metrics are seasonal is a contradiction an agent would be right
to be confused by.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from core.config import get_settings
from simulator.cluster import CLUSTER, NAMESPACE, Pod
from simulator.metrics_generator import SECONDS_PER_DAY, diurnal, weekly

#: An upper bound on the baseline log rate of the busiest pod at its busiest
#: hour, in lines per simulated second. Used only to size sampling, so it wants
#: to be a ceiling rather than an estimate - the busiest pod is checkout at
#: 180 rps, one line per twenty requests, times the 1.55 seasonal peak.
PEAK_BASELINE_RATE = 180.0 / 20.0 * 1.55

#: Log templates by key. Scenarios reference these keys, so a scenario naming a
#: template that does not exist fails at load rather than emitting nothing.
TEMPLATES: dict[str, str] = {
    "request": (
        '{{"ts":"{ts}","level":"info","msg":"request completed",'
        '"method":"{method}","path":"{path}","status":{status},"duration_ms":{duration_ms}}}'
    ),
    "request_error": (
        '{{"ts":"{ts}","level":"error","msg":"request failed",'
        '"method":"{method}","path":"{path}","status":{status},"duration_ms":{duration_ms},'
        '"error":"upstream returned 500"}}'
    ),
    "gc_pause": (
        '{{"ts":"{ts}","level":"warn","msg":"GC pause exceeded target",'
        '"pause_ms":{pause_ms},"heap_used_mb":{heap_used_mb},"heap_max_mb":{heap_max_mb}}}'
    ),
    "pool_warning": (
        '{{"ts":"{ts}","level":"warn","msg":"connection pool nearing capacity",'
        '"in_use":{in_use},"max":{pool_max},"wait_ms":{wait_ms}}}'
    ),
    "pool_exhausted": (
        '{{"ts":"{ts}","level":"error","msg":"connection pool exhausted",'
        '"in_use":{pool_max},"max":{pool_max},"waited_ms":{wait_ms}}}'
    ),
    "stack_trace": (
        '{{"ts":"{ts}","level":"error","msg":"unhandled exception",'
        '"exception":"java.lang.OutOfMemoryError: Java heap space",'
        '"stack":"at com.acme.{service}.Handler.process(Handler.java:{line})\\n'
        "\\tat com.acme.{service}.Router.dispatch(Router.java:{line2})\\n"
        '\\tat java.base/java.lang.Thread.run(Thread.java:840)"}}'
    ),
    "oom_killed": (
        '{{"ts":"{ts}","level":"error","msg":"container killed",'
        '"reason":"OOMKilled","limit_mb":{heap_max_mb},"usage_mb":{heap_used_mb}}}'
    ),
    "disk_warning": (
        '{{"ts":"{ts}","level":"warn","msg":"disk usage high",'
        '"mount":"/var/lib/containerd","used_percent":{used_percent}}}'
    ),
    "throttled": (
        '{{"ts":"{ts}","level":"warn","msg":"cpu throttled",'
        '"throttled_periods":{throttled},"periods":{periods}}}'
    ),
    "test_flake": (
        '{{"ts":"{ts}","level":"error","msg":"test failed",'
        '"suite":"{suite}","test":"{test}","attempt":{attempt},'
        '"error":"timed out waiting for condition after 30s"}}'
    ),
}

PATHS = ("/api/checkout", "/api/cart", "/api/catalog/search", "/api/payments/authorize", "/healthz")
METHODS = ("GET", "POST", "PUT")
SUITES = ("integration.CheckoutFlow", "integration.PaymentGateway", "unit.CartTotals")
TESTS = ("testConcurrentCheckout", "testRetryOnTimeout", "testIdempotentAuthorize")


@dataclass(slots=True)
class LogLine:
    """One rendered line, with the labels Loki will index."""

    pod: Pod
    level: str
    line: str


#: The `job` label on every stream pushed to Loki, and the only place it is
#: written. Distinct from `PUSHGATEWAY_JOB` by intent even though they currently
#: share a value: one identifies a pushgateway group, the other a Loki stream,
#: and they belong to different systems that could diverge.
#:
#: Named because the spelling of an identity used in two directions is where
#: this repository lost a week - see PUSHGATEWAY_JOB.
LOKI_JOB_LABEL = "pantheon-sim"


class LogGenerator:
    """Renders lines for pods and ships them to Loki."""

    def __init__(
        self,
        loki_url: str | None = None,
        seed: int = 20260817,
        target_lines_per_pod_per_tick: float = 25.0,
    ) -> None:
        self.loki_url = (loki_url or get_settings().loki.base).rstrip("/")
        self.target_lines_per_pod_per_tick = target_lines_per_pod_per_tick
        self._rng = np.random.default_rng(seed)

    # -- rendering --------------------------------------------------------

    def render(self, template: str, pod: Pod, simulated_seconds: float) -> str:
        """Fill a template with plausible values.

        Values vary per line so a clusterer has something to mask. A template
        rendered identically every time collapses to a single cluster and makes
        the log stream trivially compressible - and useless as a test.
        """
        rng = self._rng
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fields = {
            "ts": stamp,
            "method": METHODS[rng.integers(len(METHODS))],
            "path": PATHS[rng.integers(len(PATHS))],
            "status": int(rng.choice([200, 200, 200, 201, 204, 500])),
            "duration_ms": int(abs(rng.normal(pod.base_latency_seconds * 1000, 40)) + 1),
            "pause_ms": int(abs(rng.normal(180, 90)) + 20),
            "heap_used_mb": int(pod.base_memory_bytes / 1024**2 * rng.uniform(0.7, 0.98)),
            "heap_max_mb": int(pod.base_memory_bytes / 1024**2 * 1.25),
            "in_use": int(rng.integers(40, 50)),
            "pool_max": 50,
            "wait_ms": int(abs(rng.normal(2500, 900)) + 100),
            "service": pod.service,
            "line": int(rng.integers(80, 400)),
            "line2": int(rng.integers(80, 400)),
            "used_percent": round(float(rng.uniform(86.0, 97.5)), 1),
            "throttled": int(rng.integers(120, 400)),
            "periods": 500,
            "suite": SUITES[rng.integers(len(SUITES))],
            "test": TESTS[rng.integers(len(TESTS))],
            "attempt": int(rng.integers(1, 4)),
        }
        return TEMPLATES[template].format(**fields)

    def baseline_rate(self, pod: Pod, simulated_seconds: float) -> float:
        """Baseline lines per simulated second, following the same curve as metrics."""
        day_fraction = (simulated_seconds % SECONDS_PER_DAY) / SECONDS_PER_DAY
        season = 1.0 + diurnal(day_fraction) * 0.55
        # One log line per twenty requests; a line per request would drown Loki
        # without teaching an agent anything extra.
        return max(pod.base_rps / 20.0 * season * weekly(simulated_seconds), 0.05)

    def sampling_ratio(self, interval: float) -> float:
        """The fraction of lines actually emitted, given how much time a tick covers.

        Compressed time means a tick can represent fifteen simulated minutes, and
        emitting every line of it would spend the whole run talking to Loki.

        The important part is that this is one ratio for the entire run, derived
        from the tick length and a fixed peak rate — never from the current
        value. Clipping each pod at a per-tick ceiling would be easier and would
        be wrong: the busiest pod at 14:00 would emit exactly as many lines as
        the quietest pod at 04:00, erasing both the diurnal shape and the
        difference between services. That is the flat line this simulator exists
        to avoid, moved from the metric domain into the log domain.

        A uniform ratio preserves every relative volume. It is reported on the
        run report so the sampling is visible rather than silent.
        """
        expected_peak = PEAK_BASELINE_RATE * interval
        if expected_peak <= 0.0:
            return 1.0
        return min(1.0, self.target_lines_per_pod_per_tick / expected_peak)

    def baseline_lines(self, pod: Pod, simulated_seconds: float, interval: float) -> list[LogLine]:
        """Ordinary traffic for one tick, uniformly sampled."""
        expected = self.baseline_rate(pod, simulated_seconds) * interval
        count = int(self._rng.poisson(expected * self.sampling_ratio(interval)))

        lines: list[LogLine] = []
        for _ in range(count):
            # A small share of ordinary traffic fails even when nothing is wrong.
            error = self._rng.random() < 0.004
            template = "request_error" if error else "request"
            lines.append(
                LogLine(
                    pod=pod,
                    level="error" if error else "info",
                    line=self.render(template, pod, simulated_seconds),
                )
            )
        if self._rng.random() < 0.02 * interval / 60.0 * self.sampling_ratio(interval):
            lines.append(LogLine(pod, "warn", self.render("gc_pause", pod, simulated_seconds)))
        return lines

    def phase_lines(
        self,
        pod: Pod,
        template: str,
        per_minute: float,
        level: str,
        interval: float,
        simulated_seconds: float,
    ) -> list[LogLine]:
        """Lines a scenario phase adds on top of the baseline."""
        expected = per_minute * interval / 60.0
        count = int(self._rng.poisson(expected * self.sampling_ratio(interval)))
        return [
            LogLine(pod, level, self.render(template, pod, simulated_seconds)) for _ in range(count)
        ]

    # -- shipping ---------------------------------------------------------

    def push(self, lines: list[LogLine], client: httpx.Client) -> int:
        """Ship lines to Loki, one stream per (pod, level).

        Loki rejects out-of-order writes within a stream, so timestamps are
        assigned here in monotonic order rather than taken from simulated time -
        compressed time would otherwise deliver several lines at the same
        nanosecond and lose most of them.
        """
        if not lines:
            return 0

        streams: dict[tuple[str, str], list[LogLine]] = {}
        for entry in lines:
            streams.setdefault((entry.pod.name, entry.level), []).append(entry)

        now_ns = time.time_ns()
        payload: dict[str, list[dict[str, Any]]] = {"streams": []}
        for (pod_name, level), grouped in streams.items():
            pod = grouped[0].pod
            values = [[str(now_ns + index), entry.line] for index, entry in enumerate(grouped)]
            payload["streams"].append(
                {
                    "stream": {
                        "job": LOKI_JOB_LABEL,
                        "pod": pod_name,
                        "node": pod.node,
                        "service": pod.service,
                        "namespace": NAMESPACE,
                        "cluster": CLUSTER,
                        "level": level,
                    },
                    "values": values,
                }
            )

        response = client.post(
            f"{self.loki_url}/loki/api/v1/push",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return len(lines)


# TODO: Phase 5 - add multi-line stack traces as genuine multi-line entries
