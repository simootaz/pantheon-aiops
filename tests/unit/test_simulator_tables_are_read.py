"""Every per-metric table entry reaches the exported series.

`metrics_generator.py` states that every series carries a diurnal cycle, a
weekly component and gaussian noise, and cites
`tests/integration/test_simulator_data.py` for it. That file queries three
series by name - `pantheon_pod_cpu_cores`, `pantheon_http_request_duration_seconds`
and `pantheon_http_requests_total` - and never iterates `MetricName`. Five of
the eight exported families were outside its scope, and `disk_used` was one of
them: `_node_disk()` built its value from scratch and never called `_baseline`,
so `NOISE[DISK_USED]` and `SEASONAL_AMPLITUDE[DISK_USED]` were declared,
complete in both tables, and read by nothing.

`require_every_metric` did not catch it and could not: it asserts a table has an
entry for every metric, which is a claim about the table and not about whether
anything consumes it. A completeness check and a sample check sitting side by
side look like coverage of both axes and are not.

So this asserts the property the docstring claims, over the quantifier it claims
it for: **for every metric and every table, perturbing that metric's entry
changes what the exporter emits.** It goes through `push()` with a stub client
rather than through `sample()`, because the defect was that `push()` reached a
value by a path `sample()` was not on.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from simulator import metrics_generator as generator_module
from simulator.metrics_generator import (
    NOISE,
    SEASONAL_AMPLITUDE,
    SECONDS_PER_DAY,
    WEEKLY_AMPLITUDE,
    MetricsGenerator,
)
from simulator.scenario import MetricName

#: The exported family each metric feeds, and the label selecting its samples.
#:
#: Complete by assertion, not by convention - `test_every_metric_names_its_family`
#: fails if a metric is added without one, which is the gap that let `disk_used`
#: go unexported-through-`_baseline` for the life of the branch.
FAMILY: dict[MetricName, tuple[str, dict[str, str]]] = {
    MetricName.CPU: ("pantheon_pod_cpu_cores", {}),
    MetricName.MEMORY: ("pantheon_pod_memory_working_set_bytes", {}),
    MetricName.LATENCY: ("pantheon_http_request_duration_seconds", {}),
    MetricName.REQUEST_RATE: ("pantheon_http_requests_total", {"status": "200"}),
    MetricName.ERROR_RATE: ("pantheon_http_requests_total", {"status": "500"}),
    MetricName.RESTARTS: ("pantheon_pod_container_restarts_total", {}),
    MetricName.DISK_USED: ("pantheon_node_disk_used_bytes", {}),
    MetricName.CI_FAILURE_RATIO: ("pantheon_ci_pipeline_failure_ratio", {}),
}

#: A weekday afternoon and a weekend afternoon, so the weekly table has
#: something to change.
WEEKDAY = 2 * SECONDS_PER_DAY + 0.6 * SECONDS_PER_DAY
WEEKEND = 5 * SECONDS_PER_DAY + 0.6 * SECONDS_PER_DAY

TABLES = {
    "SEASONAL_AMPLITUDE": SEASONAL_AMPLITUDE,
    "NOISE": NOISE,
    "WEEKLY_AMPLITUDE": WEEKLY_AMPLITUDE,
}


class _Response:
    def raise_for_status(self) -> None:
        return None


class _CapturingClient:
    """Stands in for the httpx client so `push` runs without a gateway."""

    def __init__(self) -> None:
        self.body = ""

    def put(self, _url: str, content: bytes, headers: dict[str, str]) -> _Response:
        self.body = content.decode("utf-8")
        return _Response()


def _exported(seconds: float) -> dict[str, list[float]]:
    """Run the real export path and return every sample, keyed by family."""
    client = _CapturingClient()
    MetricsGenerator().push(seconds, [], interval=1.0, client=cast(httpx.Client, client))

    out: dict[str, list[float]] = {}
    for family in text_string_to_metric_families(client.body):
        for sample in family.samples:
            key = sample.name
            if sample.labels.get("status"):
                key = f"{sample.name}|status={sample.labels['status']}"
            out.setdefault(key, []).append(sample.value)
    return out


def _values(exported: dict[str, list[float]], metric: MetricName) -> list[float]:
    name, labels = FAMILY[metric]
    key = f"{name}|status={labels['status']}" if labels else name
    if key in exported:
        return exported[key]
    # Counters are exposed with a `_total` suffix the registry adds or strips
    # depending on the client version; try the other spelling before failing.
    alternative = key[: -len("_total")] if key.endswith("_total") else f"{key}_total"
    return exported.get(alternative, [])


def test_every_metric_names_its_family() -> None:
    """A metric added without a family here would skip every check below."""
    missing = set(MetricName) - set(FAMILY)
    assert not missing, (
        f"metrics with no exported family declared: {sorted(m.value for m in missing)}. "
        "Add it to FAMILY, or this file silently stops covering it - which is the "
        "exact shape of the defect it exists to prevent."
    )


def test_every_metric_reaches_the_exporter() -> None:
    """Before asking whether a table is read, check the series exists at all."""
    exported = _exported(WEEKDAY)
    absent = sorted(m.value for m in MetricName if not _values(exported, m))
    assert not absent, f"declared metrics that no exported series carries: {absent}"


@pytest.mark.parametrize("metric", list(MetricName), ids=lambda m: m.value)
@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_perturbing_a_table_entry_changes_the_export(
    metric: MetricName, table_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declared value is read by the path that builds the exported series.

    `disk_used` failed this before `_node_disk` was rewritten to derive the
    node's usage from its pods, and it failed for all three tables at once -
    the value was `0.34 * capacity` plus a drift, and nothing else.
    """
    if metric is MetricName.RESTARTS:
        pytest.skip("covered by test_restarts_declares_zero_and_means_it")

    seconds = WEEKEND if table_name == "WEEKLY_AMPLITUDE" else WEEKDAY
    before = _values(_exported(seconds), metric)

    table: dict[MetricName, float] = TABLES[table_name]
    perturbed = dict(table)
    perturbed[metric] = 0.5 if table[metric] == 0.0 else 0.0
    monkeypatch.setattr(generator_module, table_name, perturbed)
    for name, live in TABLES.items():
        if name != table_name:
            monkeypatch.setattr(generator_module, name, live)

    after = _values(_exported(seconds), metric)

    assert before != after, (
        f"changing {table_name}[{metric.value}] from {table[metric]} to "
        f"{perturbed[metric]} left every exported sample identical. The entry is "
        "declared and nothing reads it, so the series does not carry the "
        "property the module docstring claims it does."
    )


def test_restarts_declares_zero_and_means_it() -> None:
    """The one metric the perturbation test cannot cover, stated rather than skipped.

    A healthy pod restarts exactly zero times, and `_baseline` scales both the
    seasonal term and the noise by the base value - so on a base of zero neither
    table can have any effect, whatever it says. That is why the declarations
    are zero, and asserting it here means a future non-zero value fails the
    build instead of sitting in the table doing nothing.
    """
    assert SEASONAL_AMPLITUDE[MetricName.RESTARTS] == 0.0, (
        "a non-zero seasonal amplitude for restarts would be inert: `_baseline` "
        "multiplies it by a base of zero. Declare the intent some other way."
    )
    assert NOISE[MetricName.RESTARTS] == 0.0, (
        "a non-zero noise for restarts would be inert for the same reason, and "
        "would also invent restarts nothing caused."
    )

    values = _values(_exported(WEEKDAY), MetricName.RESTARTS)
    assert values and all(v == 0.0 for v in values), (
        f"a clean baseline reported non-zero restarts: {values[:5]}"
    )


def test_disk_is_not_traffic_shaped() -> None:
    """Disk keeps its level at the weekend; every other metric does not.

    The regression this guards is the one that nearly shipped with the fix:
    routing node disk through `_baseline` with a single global weekly multiplier
    would have dropped `disk_ratio` to 0.245 at weekends and put the
    `disk_pressure` fault peak at 0.636, under the 0.75 its alert rule fires at.
    """
    assert WEEKLY_AMPLITUDE[MetricName.DISK_USED] == 0.0, (
        "bytes on disk do not fall by a quarter because it is Saturday"
    )

    weekday = _values(_exported(WEEKDAY), MetricName.DISK_USED)
    weekend = _values(_exported(WEEKEND), MetricName.DISK_USED)
    ratio = sum(weekend) / sum(weekday)
    assert 0.97 < ratio < 1.03, (
        f"weekend disk is {ratio:.3f} of weekday disk; a level that accumulates "
        "should not follow the traffic rhythm"
    )

    traffic = _values(_exported(WEEKEND), MetricName.CPU)
    weekday_cpu = _values(_exported(WEEKDAY), MetricName.CPU)
    assert sum(traffic) < 0.85 * sum(weekday_cpu), (
        "cpu did not drop at the weekend, so this test would pass for disk "
        "whether or not the weekly table were read at all"
    )
