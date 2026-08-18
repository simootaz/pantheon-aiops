"""Synthesises GitLab pipeline and merge-request webhooks.

Posts to the **real** endpoint over **real HTTP**, exactly as GitLab would:
same URL, same `X-Gitlab-Event` header, same payload shape. There is no
simulator-only route and no bypass.

That matters more than it looks. If the simulator posted to a special endpoint,
the path exercised in development would not be the path exercised in production,
and the simulator would be worth less the more it was relied on. A guard in
`tests/unit/test_webhooks.py` keeps the endpoint free of any knowledge that this
module exists.

Payload shapes follow GitLab's documented Pipeline Hook and Merge Request Hook.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from core.config import get_settings

#: Sample payload data. GitLab puts a web_url in its hooks, so the fixture
#: carries one; it is never fetched, and it is not configuration.
SAMPLE_GITLAB_HOST = "https://gitlab.example.com"
PROJECT = "acme/checkout"
PROJECT_ID = 4711
BRANCHES = ("main", "feature/pool-size", "feature/retry-budget", "hotfix/timeouts")
JOBS = ("build", "unit", "integration", "lint", "package", "deploy")


@dataclass(slots=True)
class PipelineResult:
    """What was sent, so a run can report it and a test can assert on it."""

    event: str
    status: str
    pipeline_id: int
    failed_jobs: list[str]
    http_status: int
    investigation_id: str | None


class PipelineGenerator:
    """Builds GitLab-shaped payloads and posts them to the webhook."""

    def __init__(self, webhook_url: str | None = None, seed: int = 20260817) -> None:
        self.webhook_url = webhook_url or get_settings().simulator.webhook
        self._rng = np.random.default_rng(seed)
        self._next_id = PROJECT_ID

    def _pipeline_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def pipeline_payload(
        self,
        *,
        status: str = "success",
        failed_jobs: list[str] | None = None,
        ref: str | None = None,
    ) -> dict[str, Any]:
        """A GitLab Pipeline Hook body."""
        failed = failed_jobs or []
        durations = {job: round(float(abs(self._rng.normal(45, 20)) + 5), 1) for job in JOBS}
        builds: list[dict[str, Any]] = [
            {
                "id": int(self._rng.integers(10_000, 99_999)),
                "stage": "test" if job in {"unit", "integration"} else "build",
                "name": job,
                "status": "failed" if job in failed else "success",
                "duration": durations[job],
            }
            for job in JOBS
        ]
        return {
            "object_kind": "pipeline",
            "object_attributes": {
                "id": self._pipeline_id(),
                "ref": ref or str(self._rng.choice(BRANCHES)),
                "sha": f"{int(self._rng.integers(0, 16**8)):08x}",
                "status": status,
                "duration": int(sum(durations.values())),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            },
            "project": {
                "id": PROJECT_ID,
                "name": PROJECT.split("/")[-1],
                "path_with_namespace": PROJECT,
                "web_url": f"{SAMPLE_GITLAB_HOST}/{PROJECT}",
            },
            "user": {"name": "CI", "username": "ci-bot"},
            "builds": builds,
        }

    def merge_request_payload(self, *, action: str = "open") -> dict[str, Any]:
        """A GitLab Merge Request Hook body."""
        return {
            "object_kind": "merge_request",
            "object_attributes": {
                "iid": int(self._rng.integers(50, 400)),
                "title": str(
                    self._rng.choice(
                        [
                            "Raise connection pool size to 80",
                            "Add retry budget to checkout client",
                            "Cache catalog lookups for 30s",
                        ]
                    )
                ),
                "state": "opened" if action == "open" else "merged",
                "action": action,
                "source_branch": str(self._rng.choice(BRANCHES[1:])),
                "target_branch": "main",
                "last_commit": {"id": f"{int(self._rng.integers(0, 16**8)):08x}"},
            },
            "project": {
                "id": PROJECT_ID,
                "path_with_namespace": PROJECT,
                "web_url": f"{SAMPLE_GITLAB_HOST}/{PROJECT}",
            },
            "user": {"name": "Dana Okafor", "username": "dokafor"},
        }

    def send(self, client: httpx.Client, payload: dict[str, Any], event: str) -> PipelineResult:
        """POST as GitLab would, and report what came back."""
        response = client.post(
            self.webhook_url,
            json=payload,
            headers={"Content-Type": "application/json", "X-Gitlab-Event": event},
        )
        body: dict[str, Any] = {}
        if response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()

        attributes = payload["object_attributes"]
        return PipelineResult(
            event=event,
            status=str(attributes.get("status", attributes.get("action", "?"))),
            pipeline_id=int(attributes.get("id", attributes.get("iid", 0))),
            failed_jobs=[
                build["name"]
                for build in payload.get("builds", [])
                if build.get("status") == "failed"
            ],
            http_status=response.status_code,
            investigation_id=body.get("investigation_id"),
        )

    def send_pipeline(
        self,
        client: httpx.Client,
        *,
        status: str = "success",
        failed_jobs: list[str] | None = None,
        ref: str | None = None,
    ) -> PipelineResult:
        payload = self.pipeline_payload(status=status, failed_jobs=failed_jobs, ref=ref)
        return self.send(client, payload, "Pipeline Hook")

    def send_merge_request(self, client: httpx.Client, *, action: str = "open") -> PipelineResult:
        return self.send(client, self.merge_request_payload(action=action), "Merge Request Hook")


# TODO: Phase 4 - add GitHub Actions payloads once that connector exists
