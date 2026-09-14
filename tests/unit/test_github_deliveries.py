"""Simulated GitHub deliveries, sent to the real webhook with a real secret.

WHY THESE GO THROUGH THE ACTUAL ENDPOINT
------------------------------------------
`simulator/pipeline_generator.py` promises "no simulator-only route and no
bypass". A test against a mock transport can check the headers the generator
sets and cannot check that the receiver accepts them - and the failure worth
catching is exactly a disagreement between the two: a signature over a
different serialisation than the one posted, which the generator's own tests
would pass and every real delivery would fail.

So the receiver here is `create_app` with `GITHUB_WEBHOOK_SECRET` set, and the
only substitution is the investigation runner, so nothing reaches GitHub.

THE RUNNER USED TO SEND DELIVERIES THAT INVESTIGATED NOTHING
--------------------------------------------------------------
It sent GitLab pipeline hooks. Every one was a 202 and none started a run,
because `classifier.subject_of` reads GitHub's shapes. `investigating` is
asserted below for that reason: a 202 is what the broken version returned too.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.bus import InMemoryEventBus
from core.config import get_settings
from simulator.pipeline_generator import GitHubGenerator

SECRET = "simulated-delivery-secret"


class _Recorder:
    """Stands in for the investigation runner, so nothing reaches GitHub."""

    def __init__(self) -> None:
        self.triggers: list[Any] = []

    async def __call__(
        self,
        *,
        trigger: Any,
        investigation_id: Any,
        store: Any,
        bus: Any,
        gate: Any = None,
    ) -> None:
        self.triggers.append(trigger)


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, _Recorder]]:
    """The real app, verifying signatures."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    recorder = _Recorder()
    app = create_app(event_bus=InMemoryEventBus())
    app.state.investigation_runner = recorder
    try:
        with TestClient(app) as client:
            yield client, recorder
    finally:
        get_settings.cache_clear()


def _generator(secret: str = SECRET) -> GitHubGenerator:
    return GitHubGenerator(webhook_url="/webhooks/github", secret=secret)


# --- through the real receiver ---------------------------------------------------------


def test_a_failed_run_is_accepted_and_starts_an_investigation(
    receiver: tuple[TestClient, _Recorder],
) -> None:
    """The delivery the scenario runner sends for a `test_flake` phase."""
    client, recorder = receiver

    result = _generator().send_workflow_run(client, conclusion="failure")

    assert result.http_status == 202
    assert result.investigating is True, (
        "accepted and not investigated - the exact outcome of every GitLab pipeline "
        "hook this runner used to send"
    )
    assert len(recorder.triggers) == 1


def test_a_green_run_is_accepted_and_investigates_nothing(
    receiver: tuple[TestClient, _Recorder],
) -> None:
    """The control. A system that investigated every passing build would teach
    people to ignore it, and a generator whose failures and successes both
    started runs would pass the test above for the wrong reason."""
    client, recorder = receiver

    result = _generator().send_workflow_run(client, conclusion="success")

    assert result.http_status == 202
    assert result.investigating is False
    assert recorder.triggers == []


def test_a_pull_request_delivery_starts_an_investigation(
    receiver: tuple[TestClient, _Recorder],
) -> None:
    """What reaches Aegis."""
    client, recorder = receiver

    result = _generator().send_pull_request(client)

    assert result.http_status == 202
    assert result.investigating is True
    (trigger,) = recorder.triggers
    assert trigger.payload["repository"]["full_name"] == "acme/checkout"


def test_a_delivery_signed_with_the_wrong_secret_is_refused(
    receiver: tuple[TestClient, _Recorder],
) -> None:
    """Proof the receiver is actually verifying.

    Without it, the three tests above would pass against a receiver with
    verification switched off - and "the generator signs correctly" would be a
    claim no test had tested.
    """
    client, recorder = receiver

    result = _generator(secret="not-the-secret").send_workflow_run(client, conclusion="failure")

    assert result.http_status == 401
    assert recorder.triggers == []


# --- what goes on the wire --------------------------------------------------------------


def _captured(generator: GitHubGenerator) -> httpx.Request:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"investigation_id": "x", "investigating": True})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api") as client:
        generator.send_workflow_run(client, conclusion="failure")
    return seen[0]


def test_the_signature_is_over_the_bytes_that_were_posted() -> None:
    """Recomputed from the request body as it left, not from the payload dict.

    A generator that posted `json=payload` and signed its own `json.dumps` would
    agree with itself here only by luck of the two serialisers matching - and
    this recomputes from `request.content`, which is the only thing a receiver
    ever sees.
    """
    request = _captured(_generator())

    expected = "sha256=" + hmac.new(SECRET.encode(), request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-Hub-Signature-256"] == expected
    assert request.headers["X-GitHub-Event"] == "workflow_run"


def test_no_secret_means_no_signature_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """What GitHub does with no secret configured.

    An empty `sha256=` header would be a signature that claims to verify
    something, and a receiver that later gains a secret would refuse it with a
    message about a bad signature rather than a missing one.
    """
    request = _captured(_generator(secret=""))

    assert "X-Hub-Signature-256" not in request.headers


def test_the_secret_defaults_to_the_one_the_receiver_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """One setting, read by both sides - as GitHub and the receiver share one.

    A generator with its own secret setting would be a second place to
    configure, and the two would disagree the first time only one was rotated.
    """
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        request = _captured(GitHubGenerator(webhook_url="/webhooks/github"))
    finally:
        get_settings.cache_clear()

    expected = "sha256=" + hmac.new(SECRET.encode(), request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-Hub-Signature-256"] == expected


def test_run_ids_do_not_repeat() -> None:
    """Two runs sharing an id are one run to anything that keys on it."""
    generator = _generator()
    ids = {generator.workflow_run_payload()["workflow_run"]["id"] for _ in range(10)}

    assert len(ids) == 10


def test_a_delivery_carries_no_url_nothing_reads() -> None:
    """No `html_url`, deliberately.

    Nothing reads one, and carrying it would need an exemption from the
    hardcoded-endpoint guard - a hole the next real endpoint could walk through.
    """
    generator = _generator()

    for payload in (generator.workflow_run_payload(), generator.pull_request_payload()):
        assert "http" not in str(payload)
