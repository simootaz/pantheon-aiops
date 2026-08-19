"""Guards over the simulator's alerting rules.

Two properties matter here and neither is obvious from reading a rule.

**A rule must be able to fire.** `for:` and range selectors are wall-clock, but
a fault lasting D simulated seconds is only visible for D/speed wall seconds. A
`for: 5m` clause against a 47-second fault window is not a strict rule, it is an
unfirable one, and nothing about the YAML says so.

**A rule must mean the same thing at every speed.** Counters read `speed` times
faster than the rate they represent, so `rate(x[10s]) > 5` fires at 500x and
never at 1x. Gauges and ratios are immune; nothing else is.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from simulator.alerting import BUDGET_FRACTION, can_fire_at, fault_seconds, max_speed_for
from simulator.scenario import Scenario, load_all
from tests.mechanism import read_data, read_verbatim

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES = REPO_ROOT / "deploy" / "observability" / "prometheus" / "rules.sim.yml"
ALERTMANAGER = REPO_ROOT / "deploy" / "observability" / "alertmanager" / "alertmanager.sim.yml"

#: The compression the rule windows are sized against. The gate runs here, and
#: `test_every_rule_can_fire_within_its_scenarios_fault_window` checks the
#: inequality at this speed.
REFERENCE_SPEED = 240.0

DURATION = re.compile(r"^(\d+)(ms|s|m|h)$")
UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
#: Any range selector in an expression, e.g. `[10s]`.
RANGE_SELECTOR = re.compile(r"\[(\d+)(ms|s|m|h)\]")
#: Any offset modifier, e.g. `offset 30s`. Counted because a rule comparing a
#: series against itself 30 seconds ago needs those 30 seconds of history before
#: it can evaluate, exactly as a range selector does.
#:
#: This was missed on the first pass - the scanner enumerated range selectors
#: only, so switching the memory rule to `offset` made it look like it needed
#: 10s when it needs 40, and the derived gate speed jumped to a value at which
#: it could never fire. The fourth too-narrow scanner in this repository, and
#: the same lesson each time: enumerate every form of the thing being measured.
OFFSET_MODIFIER = re.compile(r"offset\s+(\d+)(ms|s|m|h)")


def seconds(literal: str) -> float:
    match = DURATION.match(literal.strip())
    assert match, f"{literal!r} is not a Prometheus duration"
    return int(match.group(1)) * UNITS[match.group(2)]


def rules() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(read_data(RULES))
    return [rule for group in loaded["groups"] for rule in group["rules"]]


def rule_seconds(rule: dict[str, Any]) -> float:
    """Wall time that must elapse before a rule can fire.

    The longest look-back in the expression - a range selector or an offset,
    whichever reaches further - plus the `for:` hold.
    """
    lookbacks = [
        int(n) * UNITS[u]
        for pattern in (RANGE_SELECTOR, OFFSET_MODIFIER)
        for n, u in pattern.findall(rule["expr"])
    ]
    return (max(lookbacks) if lookbacks else 0.0) + seconds(str(rule["for"]))


def test_the_lookback_scanner_sees_both_forms() -> None:
    """Both directions on the scanner, because it sets every gate speed."""
    ranged = {"expr": "avg_over_time(x[45s]) > 1", "for": "10s"}
    offset = {"expr": "x > 1.5 * (x offset 30s)", "for": "10s"}
    neither = {"expr": "x > 5", "for": "10s"}

    assert rule_seconds(ranged) == 55.0
    assert rule_seconds(offset) == 40.0, "an offset look-back was not counted"
    assert rule_seconds(neither) == 10.0


def scenarios() -> dict[str, Scenario]:
    return {scenario.name: scenario for scenario in load_all()}


# --- every scenario has a rule, and every rule has a scenario ----------------


def test_every_scenario_has_at_least_one_alerting_rule() -> None:
    """Flow 1 cannot run for a scenario nothing alerts on."""
    covered = {rule["labels"]["scenario"] for rule in rules()}
    missing = sorted(set(scenarios()) - covered)
    assert not missing, (
        f"scenarios with no alerting rule: {missing}. Nothing can trigger an "
        "investigation from them, so the alert path is untested for those."
    )


def test_every_rule_names_a_scenario_that_exists() -> None:
    """The other direction: a rule for a deleted scenario fires on nothing."""
    known = set(scenarios())
    unknown = sorted(
        rule["labels"]["scenario"] for rule in rules() if rule["labels"]["scenario"] not in known
    )
    assert not unknown, f"rules naming scenarios that do not exist: {unknown}"


def test_every_rule_carries_the_labels_the_receiver_reads() -> None:
    """`severity` and `scenario` reach the Trigger; blank ones make it useless."""
    for rule in rules():
        labels = rule.get("labels") or {}
        assert labels.get("severity"), f"{rule['alert']} has no severity"
        assert labels.get("scenario"), f"{rule['alert']} has no scenario"
        annotations = rule.get("annotations") or {}
        assert annotations.get("summary"), f"{rule['alert']} has no summary"


# --- the compression relationship, enforced ---------------------------------


@pytest.mark.parametrize("rule", rules(), ids=lambda r: str(r["alert"]))
def test_every_rule_can_fire_within_its_scenarios_fault_window(rule: dict[str, Any]) -> None:
    """The inequality the rules file states, checked rather than trusted.

        range_window + for_duration  <  fault_simulated_duration / speed

    A `for: 5m` clause against bad_deploy_5xx - 11400 simulated seconds, so 47
    wall seconds at the reference speed - can never fire, and nothing in the
    YAML would say so. This is what stops a rule silently becoming unfirable at
    one speed and a hair trigger at another.
    """
    scenario = scenarios()[rule["labels"]["scenario"]]
    needed = rule_seconds(rule)

    assert can_fire_at(scenario, needed, REFERENCE_SPEED), (
        f"{rule['alert']} needs {needed:.0f}s of wall clock, but at "
        f"{REFERENCE_SPEED:.0f}x {scenario.name}'s fault is visible for only "
        f"{fault_seconds(scenario) / REFERENCE_SPEED:.0f}s, of which a rule may "
        f"use {BUDGET_FRACTION:.0%}. Its ceiling is "
        f"{max_speed_for(scenario, needed):.0f}x. It would never fire."
    )


@pytest.mark.parametrize("rule", rules(), ids=lambda r: str(r["alert"]))
def test_no_rule_compares_a_bare_rate_against_a_constant(rule: dict[str, Any]) -> None:
    """Counters read `speed` times fast, so only gauges and ratios are safe.

    `rate(x[10s]) > 5` fires at 500x and is unreachable at 1x - the same rule
    meaning two different things depending on a flag. A ratio of two rates has
    the factor in numerator and denominator, where it cancels exactly.
    """
    expression = " ".join(rule["expr"].split())
    if "rate(" not in expression:
        return  # a pure gauge comparison; compression cannot touch it

    assert "/" in expression, (
        f"{rule['alert']} thresholds a bare rate() against a constant. Counters "
        "scale with the compression factor, so this fires at one speed and not "
        "another. Divide by another rate, or use a gauge."
    )


def test_the_reference_speed_is_one_a_run_can_actually_deliver() -> None:
    """A window sized against a speed the runner cannot reach proves nothing."""
    from simulator.runner import DEFAULT_TICK_SECONDS, max_honest_speed

    ceiling = max_honest_speed(DEFAULT_TICK_SECONDS * 4)
    assert ceiling >= REFERENCE_SPEED, (
        f"rules are sized against {REFERENCE_SPEED:.0f}x, above the {ceiling:.0f}x "
        "a run can deliver at that tick size"
    )


# --- sim-scoped, like the config beside it -----------------------------------


@pytest.mark.parametrize("path", [RULES, ALERTMANAGER], ids=lambda p: p.name)
def test_the_sim_files_announce_that_they_must_not_be_deployed(path: Path) -> None:
    """A hair-trigger rule set is as dangerous as a 1s scrape config."""
    head = read_verbatim(path, why="the warning banner is a comment")[:900].lower()
    assert "never deploy" in head, f"{path.name} has no warning banner"
    assert "simulator only" in head, f"{path.name} does not say it is simulator-only"


@pytest.mark.parametrize("path", [RULES, ALERTMANAGER], ids=lambda p: p.name)
def test_the_sim_files_are_never_referenced_from_a_deployment_path(path: Path) -> None:
    """Same guard as prometheus.sim.yml, for the same reason."""
    from tests.mechanism import mechanism_only, read_scannable

    offenders: list[str] = []
    for root in (
        REPO_ROOT / "deploy" / part for part in ("helm", "kustomize", "argocd", "terraform")
    ):
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            if path.name in mechanism_only(read_scannable(candidate)):
                offenders.append(str(candidate.relative_to(REPO_ROOT)))

    assert not offenders, f"{path.name} is referenced from a deployment path: {offenders}"


def test_the_alertmanager_receiver_points_at_the_real_endpoint() -> None:
    """The same URL a real Alertmanager posts to; no simulator-only route."""
    config = yaml.safe_load(read_data(ALERTMANAGER))
    urls = [
        webhook["url"]
        for receiver in config["receivers"]
        for webhook in receiver.get("webhook_configs", [])
    ]
    assert urls, "alertmanager has no webhook receiver"
    for url in urls:
        assert url.endswith("/webhooks/alertmanager"), (
            f"{url} is not the endpoint the API serves. A simulator-specific "
            "route would mean the path here is not the production one."
        )
