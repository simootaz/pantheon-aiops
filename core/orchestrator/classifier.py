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
