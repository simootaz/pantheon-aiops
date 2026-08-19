"""Flow 1, end to end: a scenario runs, an alert fires, an Investigation opens.

Before this branch no scenario could fire an alert at all - the simulator wrote
metrics and nothing turned them into one - so this is the first time the trigger
half of *"an alert produces a Finding"* runs against real infrastructure.

BOTH DIRECTIONS, PER RULE
-------------------------
Each of the five rules is checked twice:

* run its scenario, and **that** alert must reach Alertmanager;
* run baseline only, and **no** alert may fire.

The negative case is the one that catches a bad rule. A threshold low enough to
fire on anything passes the positive test for every scenario and is worse than
having no rule, because it teaches whoever reads the alert to ignore it. Only
the clean run distinguishes a detector from a smoke alarm with the battery out.

THRESHOLDS AND HOLDS, STATED
----------------------------
Each is justified in `rules.sim.yml` beside the rule, against numbers measured
from the generator rather than chosen by feel:

| Alert | Fires when | Hold | Baseline / fault |
|---|---|---|---|
| CheckoutErrorRateHigh | 5xx ratio > 0.02 | 10s | 0.004 / 0.036 |
| MemoryGrowingAgainstItsOwnBaseline | > 1.5x its 90s average | 10s | ramps to 2.6x |
| NodeLatencyElevated | node worst-case > 0.45s | 10s | 0.386 peak / 0.69+ |
| NodeDiskFillingUp | used/total > 0.75 | 10s | 0.34 / 0.88 |
| CiFailureRatioHigh | failure ratio > 0.20 | 10s | 0.04 peak / 0.51 |

Run with:  make test-alerts

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from core.config import get_settings, require_stack
from simulator.alerting import gate_speed
from simulator.runner import ScenarioRunner
from simulator.scenario import load
from tests.unit.test_alert_rules import rule_seconds
from tests.unit.test_alert_rules import rules as alerting_rules

pytestmark = pytest.mark.integration

SETTINGS = get_settings()
PROMETHEUS = SETTINGS.prometheus.base
ALERTMANAGER = SETTINGS.alertmanager.base
API = f"http://localhost:{SETTINGS.api.port}"

#: Ticks are larger here than the simulator default, because a bigger tick
#: raises the compression the runner can actually hold - see max_honest_speed -
#: and these runs want to finish.
TICK_SECONDS = 300.0

#: Wall time each rule needs before it can fire, read from the rules file so the
#: gate and the rules cannot disagree. Per rule rather than one global maximum:
#: bad_deploy_5xx's rule needs 20s and disk_pressure's needs 10, and forcing the
#: whole gate to the slowest one made it four times longer for no added rigour.
RULE_SECONDS = {rule["labels"]["scenario"]: rule_seconds(rule) for rule in alerting_rules()}

#: Which alert each scenario must produce. The mapping lives in the rule labels
#: too; asserting it here from the other side means a rule relabelled to the
#: wrong scenario fails rather than quietly testing nothing.
EXPECTED_ALERT = {
    "bad_deploy_5xx": "CheckoutErrorRateHigh",
    "memory_leak": "MemoryGrowingAgainstItsOwnBaseline",
    "noisy_neighbor": "NodeLatencyElevated",
    "disk_pressure": "NodeDiskFillingUp",
    "flaky_test_storm": "CiFailureRatioHigh",
}

READY_ATTEMPTS = 60 if require_stack() else 12


def _reachable(url: str, path: str = "/") -> bool:
    try:
        return httpx.get(f"{url}{path}", timeout=2.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def stack() -> None:
    for attempt in range(READY_ATTEMPTS):
        missing = [
            name
            for name, ok in (
                ("prometheus", _reachable(PROMETHEUS, "/-/ready")),
                ("alertmanager", _reachable(ALERTMANAGER, "/-/ready")),
                ("api", _reachable(API, "/health")),
            )
            if not ok
        ]
        if not missing:
            return
        if attempt == READY_ATTEMPTS - 1:
            message = f"not reachable: {missing}. Start it with: make up"
            if require_stack():
                pytest.fail(f"{message}\nPANTHEON_REQUIRE_STACK is set: failure, not skip.")
            pytest.skip(message)
        time.sleep(1.0)


def firing() -> set[str]:
    """Alert names Alertmanager currently holds, however they got there."""
    response = httpx.get(f"{ALERTMANAGER}/api/v2/alerts", timeout=15.0)
    response.raise_for_status()
    return {alert["labels"]["alertname"] for alert in response.json()}


def prometheus_alerts() -> set[str]:
    """Alert names Prometheus itself considers firing, before Alertmanager grouping."""
    response = httpx.get(f"{PROMETHEUS}/api/v1/alerts", timeout=15.0)
    response.raise_for_status()
    return {
        alert["labels"]["alertname"]
        for alert in response.json()["data"]["alerts"]
        if alert["state"] == "firing"
    }


def reset_pushgateway() -> None:
    httpx.delete(f"http://{SETTINGS.pushgateway.host_port}/metrics/job/pantheon_sim", timeout=10.0)


def settle(seconds_to_wait: float = 25.0) -> None:
    """Let the previous run's series go stale before the next one starts.

    Without this a scenario's alert can still be firing when the baseline run
    begins, and the negative test would fail on the previous test's fault.
    """
    reset_pushgateway()
    time.sleep(seconds_to_wait)


def speed_for(name: str) -> float:
    """The compression this scenario runs at, from the shared relationship.

    Per scenario rather than one global number: disk_pressure's fault lasts
    216000 simulated seconds and does not need the slow clock bad_deploy_5xx's
    11400 requires. Deriving it keeps the gate honest and keeps it finishing.
    """
    return gate_speed(load(name), RULE_SECONDS[name], TICK_SECONDS)


def watching(run: Callable[[], object]) -> set[str]:
    """Run something, and collect every alert seen firing WHILE it runs.

    Watching during rather than asking afterwards, and the difference is not
    cosmetic. The pushgateway retains the last values pushed, so after a run
    whose fault is still active the faulty numbers persist and an absolute-
    threshold rule keeps firing indefinitely - which made three scenarios pass
    on retained state rather than on live data.

    A self-relative rule exposes that: once the run stops, the retained constant
    makes the series equal to its own past, the comparison collapses to 1, and
    the alert can never fire however long the test waits. Found by the memory
    rule doing exactly that.

    Used by the negative case too, deliberately. A clean-baseline check that
    only looks at the end would miss a rule firing transiently in the middle,
    which would make it weaker than the positive checks it is meant to qualify.
    """
    seen: set[str] = set()
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            with contextlib.suppress(httpx.HTTPError):
                seen.update(prometheus_alerts())
            time.sleep(1.5)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        run()
        # The `for:` hold may still be counting when the last tick lands. The
        # retained values keep an absolute rule true for a few more seconds,
        # enough for the hold to complete; a self-relative rule will already
        # have fired during the run or not at all.
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            with contextlib.suppress(httpx.HTTPError):
                seen.update(prometheus_alerts())
            time.sleep(1.5)
    finally:
        stop.set()
        watcher.join(timeout=5.0)
    return seen


def run_watching_for_alerts(name: str) -> set[str]:
    """Run one scenario at its derived speed, watching throughout."""
    scenario = load(name)
    speed = speed_for(name)
    return watching(
        lambda: ScenarioRunner(tick_seconds=TICK_SECONDS).run(
            scenario, speed=speed, send_pipelines=False
        )
    )


# --- the negative case, first --------------------------------------------


def test_a_clean_baseline_fires_nothing(stack: None) -> None:
    """The case that separates a detector from an always-on alarm.

    Deliberately first: if a rule fires on normal traffic, every positive test
    below is meaningless, and knowing that before reading five green ticks is
    worth the ordering.
    """
    settle()
    speed = gate_speed(load("bad_deploy_5xx"), RULE_SECONDS["bad_deploy_5xx"], TICK_SECONDS)
    seen = watching(
        lambda: ScenarioRunner(tick_seconds=TICK_SECONDS).baseline(
            speed=speed, simulated_seconds=speed * 150.0
        )
    )

    fired = seen & set(EXPECTED_ALERT.values())
    assert not fired, (
        f"{sorted(fired)} fired on a clean baseline. A rule that fires on normal "
        "traffic is worse than no rule: it trains whoever reads it to ignore the "
        "next one."
    )


# --- and then each scenario ------------------------------------------------


@pytest.mark.parametrize("scenario", sorted(EXPECTED_ALERT), ids=lambda s: str(s))
def test_each_scenario_fires_its_own_alert(scenario: str, stack: None) -> None:
    """Running the scenario must produce that scenario's alert."""
    settle()
    fired = run_watching_for_alerts(scenario)

    expected = EXPECTED_ALERT[scenario]
    assert expected in fired, (
        f"{scenario} ran at {speed_for(scenario):.0f}x but {expected} did not "
        f"fire. Firing now: {sorted(fired)}. "
        "Either the rule's threshold does not match what the generator produces, "
        "or its window is longer than the fault is visible."
    )


def test_a_firing_alert_reaches_the_receiver_over_real_http(stack: None) -> None:
    """The last hop: Prometheus to Alertmanager to POST /webhooks/alertmanager.

    Asserted against Alertmanager's own view rather than the API's, because what
    matters is that the configured route delivered - not that the endpoint would
    have accepted a payload if something had sent one, which the connector gate
    already covers.
    """
    settle()
    run_watching_for_alerts("bad_deploy_5xx")

    deadline = time.monotonic() + 45.0
    delivered: set[str] = set()
    while time.monotonic() < deadline:
        delivered = firing()
        if "CheckoutErrorRateHigh" in delivered:
            break
        time.sleep(2.0)

    assert "CheckoutErrorRateHigh" in delivered, (
        f"the alert fired in Prometheus but never reached Alertmanager. Held: {sorted(delivered)}"
    )


def test_the_alert_carries_the_scenario_label_the_rule_set(stack: None) -> None:
    """The label is how an investigation knows which ground truth to score against."""
    alerts: list[dict[str, Any]] = httpx.get(f"{ALERTMANAGER}/api/v2/alerts", timeout=15.0).json()
    matching = [a for a in alerts if a["labels"].get("alertname") == "CheckoutErrorRateHigh"]
    assert matching, "CheckoutErrorRateHigh is not held by Alertmanager"
    assert matching[0]["labels"].get("scenario") == "bad_deploy_5xx"
    assert matching[0]["labels"].get("severity") == "critical"
