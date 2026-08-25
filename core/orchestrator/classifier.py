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
from core.contracts.investigation import Trigger

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

#: The domain a metric-shaped alert belongs to. One entry, because one agent
#: detects. Every other domain is a stub, and routing to a stub would produce a
#: plan that cannot run.
METRIC_DOMAIN = "anomaly"


@dataclass(frozen=True)
class Classification:
    """What Zeus decided about a trigger, and whether it was sure.

    `certain` is carried rather than inferred from the domain, because "we
    routed this to anomaly because the label said so" and "we routed this to
    anomaly because it is the only thing that runs" are different facts and the
    plan should not present them identically.
    """

    domain: str
    severity: Severity
    certain: bool
    reason: str


def classify(trigger: Trigger) -> Classification:
    """Read the trigger's own labels. Infer nothing that is not there."""
    labels = _labels(trigger)
    severity_label = str(labels.get("severity", "")).lower()
    severity = SEVERITY_LABELS.get(severity_label, Severity.MEDIUM)

    scenario = labels.get("scenario")
    if scenario:
        return Classification(
            domain=METRIC_DOMAIN,
            severity=severity,
            certain=True,
            reason=f"alert carries scenario={scenario}, which is metric-shaped",
        )
    if labels.get("alertname"):
        return Classification(
            domain=METRIC_DOMAIN,
            severity=severity,
            certain=True,
            reason=f"alert {labels['alertname']} arrived from Alertmanager",
        )
    return Classification(
        domain=METRIC_DOMAIN,
        severity=severity,
        certain=False,
        reason=(
            "no alertname or scenario label, so the domain was not determined - "
            "this went to the only domain that has an implemented agent"
        ),
    )


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
