"""Guards over the simulator's observability stack.

The dangerous artifact here is `prometheus.sim.yml`: a 1s scrape interval, which
exists only because a pushgateway discards timestamps and a simulated day has to
be compressed into minutes. Pointed at a real cluster it would generate roughly
a hundred times the intended sample volume.

So the separation between the sim config and the production-shaped one is
enforced rather than trusted.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tests.mechanism import mechanism_only, read_data, read_mechanism, read_scannable, read_verbatim

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "compose"
PROMETHEUS = REPO_ROOT / "deploy" / "observability" / "prometheus"

SIM_CONFIG = PROMETHEUS / "prometheus.sim.yml"
PROD_CONFIG = PROMETHEUS / "prometheus.yml"

#: Anything under these trees deploys somewhere real.
DEPLOYMENT_TREES = ("deploy/helm", "deploy/kustomize", "deploy/argocd", "deploy/terraform")


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(read_data(path))
    assert isinstance(loaded, dict), f"{path.name} is not a mapping"
    return loaded


def _seconds(interval: str) -> float:
    """Parse a Prometheus duration such as `1s`, `500ms`, `15s`, `1m`."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)", interval.strip())
    assert match, f"unparseable scrape interval: {interval!r}"
    value, unit = float(match.group(1)), match.group(2)
    return value * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]


def test_both_prometheus_configs_exist_and_are_distinct() -> None:
    """One fast config for simulation, one sane config for everything else."""
    assert SIM_CONFIG.is_file(), "prometheus.sim.yml is missing"
    assert PROD_CONFIG.is_file(), "prometheus.yml is missing"
    assert read_mechanism(SIM_CONFIG) != read_mechanism(PROD_CONFIG), (
        "the sim and production Prometheus configs differ only in comments, so they "
        "are the same configuration wearing two names"
    )


def test_the_sim_config_scrapes_fast_enough_to_see_seasonality() -> None:
    """A compressed day sampled at 15s yields a handful of points.

    Seasonality would then be invisible not because the generator is wrong but
    because the transport cannot carry it.
    """
    interval = _load(SIM_CONFIG)["global"]["scrape_interval"]
    assert _seconds(interval) <= 2.0, (
        f"sim scrape_interval is {interval}; too slow to sample a compressed day densely"
    )


def test_the_production_config_is_not_fast() -> None:
    """The whole reason the two files are separate."""
    interval = _load(PROD_CONFIG)["global"]["scrape_interval"]
    assert _seconds(interval) >= 10.0, (
        f"production scrape_interval is {interval}; that is simulation-shaped and "
        "would generate ~100x the intended sample volume against a real cluster"
    )


def test_the_sim_config_is_never_referenced_from_a_deployment_path() -> None:
    """Nobody ships a 1s scrape to a real cluster.

    The sim config may be referenced by the dev Compose overlay and by
    documentation, and nowhere else.
    """
    offenders: list[str] = []
    for tree in DEPLOYMENT_TREES:
        root = REPO_ROOT / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            text = mechanism_only(read_scannable(path))
            if "prometheus.sim" in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "the simulation Prometheus config is referenced from a deployment path:\n  "
        + "\n  ".join(offenders)
    )


def test_the_sim_config_announces_that_it_must_not_be_deployed() -> None:
    """The warning belongs where someone would copy the file from."""
    head = read_verbatim(SIM_CONFIG, why="the warning banner is a comment")[:800].lower()
    assert "never deploy" in head
    assert "simulator only" in head


def test_the_dev_overlay_provides_what_the_simulator_writes_into() -> None:
    """Prometheus, Loki and a pushgateway, reachable from the dev stack."""
    dev = _load(COMPOSE / "docker-compose.dev.yml")
    services = set(dev["services"])
    for required in ("prometheus", "loki", "pushgateway"):
        assert required in services, f"dev overlay does not provide {required}"

    command = dev["services"]["prometheus"]["command"]
    assert any("prometheus.sim.yml" in str(part) for part in command), (
        "dev Prometheus is not using the simulation config"
    )


def test_the_obs_overlay_is_additive_not_an_alternative() -> None:
    """Two overlays defining the same service is a merge nobody predicted.

    Prometheus and Loki come from dev; obs layers visualisation on top. That is
    what keeps all three Compose files independently valid.
    """
    dev = set(_load(COMPOSE / "docker-compose.dev.yml")["services"])
    obs = set(_load(COMPOSE / "docker-compose.obs.yml")["services"])

    assert not (dev & obs), (
        f"dev and obs both define {sorted(dev & obs)}; composing them would merge the "
        "definitions in a way nobody intends"
    )
    assert {"grafana", "tempo", "otel-collector"} <= obs


def test_pinned_images_rather_than_latest_for_the_data_path() -> None:
    """A floating tag under the simulator makes a failed run unreproducible.

    Grafana and Tempo are visualisation and may float; anything the simulator
    writes into or reads back from is pinned, because a scenario that behaved
    differently last week is worthless as ground truth.
    """
    dev = _load(COMPOSE / "docker-compose.dev.yml")["services"]
    for name in ("prometheus", "loki", "pushgateway"):
        image = str(dev[name]["image"])
        assert not image.endswith(":latest"), f"{name} uses a floating tag: {image}"
        assert ":" in image, f"{name} has no tag at all: {image}"
