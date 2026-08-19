"""Each integration gate declares the services it needs.

A gate that needs the API cannot run in a job that starts only Prometheus. That
is not a hypothetical: `make test-sim` ran the whole directory, so the connector
and alert gates were swept into CI's simulator job and errored on a missing API
while the simulator assertions beside them all passed.

So requirements are declared per module rather than implied by which target
happens to run it:

    pytestmark = [pytest.mark.integration, requires("prometheus", "api")]

`tests/unit/test_ci_is_runnable.py` asserts every gate declares something, and
`docs/REPOSITORY_MAP.md` records which are CI-runnable and which are local-only.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx
import pytest

from core.config import get_settings, require_stack

#: Service name -> a readiness URL. One place, so a gate names a service rather
#: than repeating a URL and a health path.
SERVICES: dict[str, str] = {}


def _urls() -> dict[str, str]:
    settings = get_settings()
    return {
        "prometheus": f"{settings.prometheus.base}/-/ready",
        "loki": f"{settings.loki.base}/ready",
        "pushgateway": f"http://{settings.pushgateway.host_port}/-/ready",
        "alertmanager": f"{settings.alertmanager.base}/-/ready",
        "api": f"http://localhost:{settings.api.port}/health",
    }


def requires(*services: str) -> pytest.MarkDecorator:
    """Declare the services a gate needs to run at all."""
    unknown = sorted(set(services) - set(_urls()))
    if unknown:
        raise ValueError(f"unknown service(s) {unknown}; known: {sorted(_urls())}")
    return pytest.mark.requires_stack(*services)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "requires_stack(*services): services this gate cannot run without"
    )


def _reachable(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module", autouse=True)
def stack(request: pytest.FixtureRequest) -> Iterator[None]:
    """Skip or fail based on what this module declared it needs.

    Skipping is right on a laptop and wrong under `PANTHEON_REQUIRE_STACK`,
    where a skip would be reported as a pass by a target whose whole purpose is
    to assert against real infrastructure.
    """
    marker = request.node.get_closest_marker("requires_stack")
    needed = list(marker.args) if marker else []
    if not needed:
        yield
        return

    urls = _urls()
    attempts = 60 if require_stack() else 12
    missing: list[str] = []
    for attempt in range(attempts):
        missing = [name for name in needed if not _reachable(urls[name])]
        if not missing:
            break
        if attempt < attempts - 1:
            time.sleep(1.0)

    if missing:
        message = (
            f"{request.node.name} needs {needed}; not reachable: {missing}. "
            "Start them with: make up"
        )
        if require_stack():
            pytest.fail(
                f"{message} PANTHEON_REQUIRE_STACK is set, so this is a failure, not a skip."
            )
        pytest.skip(message)
    yield
