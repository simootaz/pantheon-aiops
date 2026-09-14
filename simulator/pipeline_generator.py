"""Synthesises forge webhooks: GitHub workflow runs and pull requests, and GitLab.

Posts to the **real** endpoint over **real HTTP**, exactly as the forge would:
same URL, same event header, same payload shape - and for GitHub, the same
HMAC signature over the same bytes. There is no simulator-only route and no
bypass.

GITHUB IS WHAT THE RUNNER SENDS
---------------------------------
The scenario runner sent GitLab pipeline hooks, and every one was accepted and
investigated nothing: `/webhooks/gitlab` schedules a run only when
`classifier.subject_of` finds a subject, and that reads GitHub's
`repository.full_name` and `workflow_run`. No gate noticed, because every
integration test runs with `send_pipelines=False`. GitHub is the forge this
deployment uses, so that is what the runner sends now. The GitLab builders stay:
the endpoint is kept, and so are the tests that describe its payloads.

WHAT THIS CAN AND CANNOT SIMULATE
-----------------------------------
It delivers the trigger, not the world the trigger refers to. A failed
`workflow_run` reaches Hephaestus, which then asks the real GitHub API about
`acme/checkout` - a repository that does not exist - and degrades, correctly,
with a finding saying so. A simulated flake verdict would need a simulated
GitHub API, and a fake API answering Hephaestus's reads would test the fake.

That matters more than it looks. If the simulator posted to a special endpoint,
the path exercised in development would not be the path exercised in production,
and the simulator would be worth less the more it was relied on. A guard in
`tests/unit/test_webhooks.py` keeps the endpoint free of any knowledge that this
module exists.

Payload shapes follow GitLab's documented Pipeline Hook and Merge Request Hook.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from core.config import get_settings

#: Sample payload data. GitLab puts a web_url in its hooks, so the fixture
#: carries one; it is never fetched, and it is not configuration.
SAMPLE_GITLAB_HOST = "https://gitlab.example.com"
#: GitHub deliveries carry no `html_url` fields, and that is deliberate.
#: Nothing reads one - the classifier reads `repository.full_name` and the run or
#: pull request number, and the agents go to the API. A fixture URL would need an
#: exemption from `test_no_hardcoded_endpoint_outside_the_config_module` to carry
#: data no reader consumes, and an exemption is a hole the next real endpoint can
#: walk through.
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
    #: Whether the receiver started an investigation. A 202 alone cannot say -
    #: the GitLab hooks this runner used to send were all 202 and all `false`.
    #: `None` when the response did not carry the field.
    investigating: bool | None = None


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
            investigating=body.get("investigating"),
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


class GitHubGenerator:
    """Builds GitHub-shaped deliveries, signs them, and posts them to the webhook.

    SIGNED OVER THE BYTES THAT ARE SENT
    -------------------------------------
    The body is serialised once, the signature is taken over those bytes, and
    those bytes are what is posted. Handing httpx a dict and signing a separate
    `json.dumps` of it would sign a different string whenever the two
    serialisers disagreed on spacing - and the receiver, which verifies the raw
    body as `api/routers/webhooks.py` insists, would refuse every delivery.

    The secret comes from the same setting the receiver reads. That is not a
    bypass: GitHub holds the secret too, and signing with it is the protocol.
    With no secret configured no signature is sent, which is also what GitHub
    does.
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        secret: str | None = None,
        repository: str = PROJECT,
        seed: int = 20260914,
    ) -> None:
        settings = get_settings()
        self.webhook_url = webhook_url or settings.simulator.github_webhook
        if secret is None:
            configured = settings.github.webhook_secret
            secret = configured.get_secret_value() if configured else ""
        self._secret = secret
        self.repository = repository
        self._rng = np.random.default_rng(seed)
        self._next_id = 9_100_000

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _sha(self) -> str:
        return "".join(f"{int(self._rng.integers(0, 16)):x}" for _ in range(40))

    def _repository(self) -> dict[str, Any]:
        owner, name = self.repository.split("/", 1)
        return {
            "id": 4711,
            "name": name,
            "full_name": self.repository,
            "owner": {"login": owner},
        }

    def workflow_run_payload(
        self,
        *,
        conclusion: str = "success",
        branch: str = "main",
        workflow: str = "ci",
    ) -> dict[str, Any]:
        """A `workflow_run` delivery with `action: completed`.

        GitHub sends one for every completion, green or not. The receiver starts
        an investigation only for a conclusion in `classifier.TRIAGEABLE`, so a
        success here is expected to come back `investigating: false`.
        """
        run_id = self._id()
        return {
            "action": "completed",
            "workflow_run": {
                "id": run_id,
                "name": workflow,
                "head_branch": branch,
                "head_sha": self._sha(),
                "run_attempt": 1,
                "status": "completed",
                "conclusion": conclusion,
                "event": "push",
            },
            "repository": self._repository(),
            "sender": {"login": "ci-bot"},
        }

    def pull_request_payload(
        self, *, action: str = "opened", number: int | None = None
    ) -> dict[str, Any]:
        """A `pull_request` delivery."""
        chosen = number if number is not None else int(self._rng.integers(50, 400))
        return {
            "action": action,
            "number": chosen,
            "pull_request": {
                "number": chosen,
                "title": str(
                    self._rng.choice(
                        [
                            "Raise connection pool size to 80",
                            "Drop the liveness probe on checkout",
                            "Cache catalog lookups for 30s",
                        ]
                    )
                ),
                "state": "open",
                "head": {"ref": str(self._rng.choice(BRANCHES[1:])), "sha": self._sha()},
                "base": {"ref": "main", "sha": self._sha()},
            },
            "repository": self._repository(),
            "sender": {"login": "dokafor"},
        }

    def sign(self, body: bytes) -> str | None:
        """`sha256=<hex>` over exactly these bytes, or `None` with no secret."""
        if not self._secret:
            return None
        return "sha256=" + hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()

    def send(self, client: httpx.Client, payload: dict[str, Any], event: str) -> PipelineResult:
        """POST as GitHub would, and report what came back."""
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "X-GitHub-Event": event}
        signature = self.sign(body)
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature

        response = client.post(self.webhook_url, content=body, headers=headers)
        reply: dict[str, Any] = {}
        if response.headers.get("content-type", "").startswith("application/json"):
            reply = response.json()

        run = payload.get("workflow_run") or {}
        change = payload.get("pull_request") or {}
        return PipelineResult(
            event=event,
            status=str(run.get("conclusion") or payload.get("action", "?")),
            pipeline_id=int(run.get("id") or change.get("number") or 0),
            failed_jobs=[],
            http_status=response.status_code,
            investigation_id=reply.get("investigation_id"),
            investigating=reply.get("investigating"),
        )

    def send_workflow_run(
        self, client: httpx.Client, *, conclusion: str = "success", branch: str = "main"
    ) -> PipelineResult:
        payload = self.workflow_run_payload(conclusion=conclusion, branch=branch)
        return self.send(client, payload, "workflow_run")

    def send_pull_request(self, client: httpx.Client, *, action: str = "opened") -> PipelineResult:
        return self.send(client, self.pull_request_payload(action=action), "pull_request")
