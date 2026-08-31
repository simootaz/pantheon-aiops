"""Classifies a trigger into an investigation domain and severity band.

DELIBERATELY RULE-BASED, AND DELIBERATELY NARROW
------------------------------------------------
Classification here reads the labels Alertmanager already set. It does not
infer, and there is no model behind it - ADR 0004's LLM gateway is unbuilt, and
a classifier that guesses is worse than one that says it does not know.

`UNKNOWN` is a real answer. A trigger nobody wrote a rule for is routed to the
default domain with `certain=False`, and the plan that follows says so. The
alternative - quietly picking the most popular domain - produces an
investigation that looks confident about a routing decision nobody made.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.contracts.finding import Severity
from core.contracts.investigation import Trigger, TriggerKind

#: Alertmanager severity labels, mapped to the contract's band. Anything else
#: lands on MEDIUM and is reported as uncertain rather than assumed.
SEVERITY_LABELS = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
}

#: What an alert is worth looking at with.
#:
#: BOTH, not one. An alert does not belong to a single domain: a human seeing a
#: 5xx spike reads the metrics AND the logs, and they answer different questions
#: about the same window. Routing to one of them and calling it "the domain"
#: was a limitation of having one implemented agent, described as a decision.
#:
#: Lethe is second because its window read is the slower of the two and the
#: dispatcher runs steps in order - not because its findings matter less.
ALERT_DOMAINS = ("anomaly", "log_clustering")

#: A question is answered, not investigated. Argus and Lethe scan a window and
#: report what moved; neither answers "what is the error rate right now", and
#: pointing them at a question produces findings nobody asked for.
QUESTION_DOMAINS = ("nl_query",)

#: A proposed change is reviewed, not investigated. Nothing has happened yet -
#: there is no window to scan and no incident to explain, so pointing Argus and
#: Lethe at a pull request would have them report on whatever the cluster was
#: doing while somebody opened it.
CHANGE_DOMAINS = ("manifest_review",)

#: A failed CI run is triaged. Same argument: the failure is in the pipeline,
#: not in the cluster, and a metric scan over the minutes around it reports the
#: weather rather than the fault.
CI_DOMAINS = ("ci_triage",)

#: Workflow-run conclusions worth triaging. A run that succeeded, was cancelled
#: or was skipped is not a failure - and starting an investigation for every
#: green build is how a system teaches people to ignore it.
TRIAGEABLE = frozenset({"failure", "timed_out"})


@dataclass(frozen=True)
class Classification:
    """What Zeus decided about a trigger, and whether it was sure.

    `certain` is carried rather than inferred from the domains, because "we
    routed this because the label said so" and "we routed this because it is
    what we always do" are different facts, and a plan should not present them
    identically.

    `domains` is a tuple, and was a single string until 2026-08-28. That
    singular shape was the reason Lethe and Hermes could be implemented,
    registered and dispatchable while remaining **unreachable** - the classifier
    could only ever name `anomaly`, so nothing routed to them and no test
    noticed. A guard now asserts every implemented agent is reachable, not
    merely registered.
    """

    domains: tuple[str, ...]
    severity: Severity
    certain: bool
    reason: str


def classify(trigger: Trigger) -> Classification:
    """Read the trigger's own labels and kind. Infer nothing that is not there."""
    labels = _labels(trigger)
    severity_label = str(labels.get("severity", "")).lower()
    severity = SEVERITY_LABELS.get(severity_label, Severity.MEDIUM)

    if question_of(trigger):
        return Classification(
            domains=QUESTION_DOMAINS,
            severity=severity,
            certain=True,
            reason="the trigger carries a question, which is answered rather than investigated",
        )

    change = pull_request_of(trigger)
    if change is not None:
        return Classification(
            domains=CHANGE_DOMAINS,
            severity=severity,
            certain=True,
            reason=(
                f"the trigger carries pull request #{change['pull_request']} on "
                f"{change['repository']}, which is reviewed rather than investigated - "
                "nothing has happened yet, so there is no window to scan"
            ),
        )

    run = failed_run_of(trigger)
    if run is not None:
        return Classification(
            domains=CI_DOMAINS,
            severity=severity,
            certain=True,
            reason=(
                f"workflow run {run['run']} on {run['repository']} finished "
                f"{run['conclusion']}; the failure is in the pipeline, not the cluster"
            ),
        )

    scenario = labels.get("scenario")
    if scenario:
        return Classification(
            domains=ALERT_DOMAINS,
            severity=severity,
            certain=True,
            reason=f"alert carries scenario={scenario}; metrics and logs both cover it",
        )
    if labels.get("alertname"):
        return Classification(
            domains=ALERT_DOMAINS,
            severity=severity,
            certain=True,
            reason=f"alert {labels['alertname']} arrived from Alertmanager",
        )
    return Classification(
        domains=ALERT_DOMAINS,
        severity=severity,
        certain=False,
        reason=(
            "no alertname, scenario or question, so the shape was not determined - "
            "metrics and logs are read because either could carry the answer, and "
            "neither is being claimed as the right one"
        ),
    )


def question_of(trigger: Trigger) -> str | None:
    """The question a human asked, when one did.

    Read from the trigger KIND as well as the payload. A payload key alone would
    make any alert carrying a field called `question` route to Hermes, and
    Alertmanager annotations are operator-supplied text.
    """
    if trigger.kind is not TriggerKind.HUMAN_QUESTION:
        return None
    value = trigger.payload.get("question")
    text = str(value).strip() if value else ""
    return text or None


def pull_request_of(trigger: Trigger) -> dict[str, Any] | None:
    """The pull request a webhook is about, when it is about one.

    Read from the trigger KIND as well as the payload, the same rule
    `question_of` follows. A payload key alone would make any alert carrying a
    field called `pull_request` route to Aegis, and Alertmanager annotations are
    operator-supplied text.

    Returns the SUBJECT rather than a bool, because the agent needs
    `repository` and `pull_request` and there is no second place that knows how
    to find them. A classifier that answered "yes, a pull request" and left the
    extraction to a dispatcher would be two readers of one payload, and the one
    that drifts is the one nobody tests.
    """
    if trigger.kind is not TriggerKind.WEBHOOK:
        return None

    change = trigger.payload.get("pull_request")
    repository = _repository_of(trigger)
    if not isinstance(change, dict) or repository is None:
        return None

    number = change.get("number")
    return {"repository": repository, "pull_request": number} if isinstance(number, int) else None


def failed_run_of(trigger: Trigger) -> dict[str, Any] | None:
    """The failed workflow run a webhook is about, when it is about one.

    A run that succeeded returns `None`. GitHub sends `workflow_run` for every
    completion, and starting an investigation for every green build is how a
    system teaches people to ignore it.
    """
    if trigger.kind is not TriggerKind.WEBHOOK:
        return None

    run = trigger.payload.get("workflow_run")
    repository = _repository_of(trigger)
    if not isinstance(run, dict) or repository is None:
        return None

    conclusion = run.get("conclusion")
    identifier = run.get("id")
    if not isinstance(identifier, int) or conclusion not in TRIAGEABLE:
        return None
    return {"repository": repository, "run": identifier, "conclusion": conclusion}


def subject_of(trigger: Trigger) -> dict[str, Any]:
    """What this trigger is ABOUT, as parameters an agent can act on.

    Empty for an alert: Argus and Lethe take a window, and the window is on the
    context already. Populated for a change or a CI run, because Aegis and
    Hephaestus are pointed at one thing and cannot find it from a time range.

    `dispatcher.py` puts this on `ctx.params`. It lives here rather than there
    because this module already reads the payload, and a second reader of the
    same payload is one that can disagree with the first.
    """
    return pull_request_of(trigger) or failed_run_of(trigger) or {}


def _repository_of(trigger: Trigger) -> str | None:
    """`owner/repo`, from GitHub's `repository.full_name`.

    Required rather than defaulted. Every tool the change and CI agents call
    takes a repository, and one guessed from a URL or a title would send a read
    at the wrong project - which answers, plausibly, about something else.
    """
    repository = trigger.payload.get("repository")
    if not isinstance(repository, dict):
        return None
    full_name = repository.get("full_name")
    return full_name if isinstance(full_name, str) and full_name else None


def scenario_of(trigger: Trigger) -> str | None:
    """The simulator scenario a trigger came from, when it names one.

    Kept on the Investigation so a run can be scored against known ground truth,
    which is the reason `Investigation.scenario` exists.
    """
    value = _labels(trigger).get("scenario")
    return str(value) if value else None


def _labels(trigger: Trigger) -> dict[str, object]:
    """Alertmanager's labels, from the payload stored verbatim by the receiver."""
    payload = trigger.payload
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts and isinstance(alerts[0], dict):
        labels = alerts[0].get("labels")
        if isinstance(labels, dict):
            return dict(labels)
    labels = payload.get("labels")
    return dict(labels) if isinstance(labels, dict) else {}
