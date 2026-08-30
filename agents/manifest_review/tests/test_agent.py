"""Aegis: what a change takes away, and what it must stay quiet about.

The tests that matter most here are the negative ones. A reviewer that reports
on the workload instead of on the change is still a reviewer that produces
findings, and it looks like it is working - so the central property is that a
protection missing from BOTH sides never appears.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agents._base.base_agent import AgentStatus
from agents._base.testing import a_context
from agents.manifest_review.agent import Aegis
from agents.manifest_review.diff import Reach, protections, reach_of, review
from agents.manifest_review.tools import IMPLEMENTATIONS
from core.contracts.finding import FindingKind, Severity


def _deployment(**overrides: Any) -> dict[str, Any]:
    """A Deployment holding every protection, so a test removes one at a time.

    Fully protected on purpose. A fixture missing a probe could not express the
    difference between "this change removed it" and "it was never there", which
    is the one distinction this agent exists to make.
    """
    manifest: dict[str, Any] = {
        "kind": "Deployment",
        "metadata": {"name": "checkout", "namespace": "shop"},
        "spec": {
            "replicas": 3,
            "strategy": {"rollingUpdate": {"maxUnavailable": 1}},
            "template": {
                "spec": {
                    "securityContext": {"runAsNonRoot": True},
                    "topologySpreadConstraints": [{"topologyKey": "kubernetes.io/hostname"}],
                    "containers": [
                        {
                            "name": "api",
                            "livenessProbe": {"httpGet": {"path": "/healthz"}},
                            "readinessProbe": {"httpGet": {"path": "/ready"}},
                            "resources": {"limits": {"cpu": "500m", "memory": "512Mi"}},
                            "securityContext": {"readOnlyRootFilesystem": True},
                        }
                    ],
                }
            },
        },
    }
    manifest.update(overrides)
    return manifest


def _without(path: list[str | int]) -> dict[str, Any]:
    """The same Deployment with one thing taken out."""
    manifest = _deployment()
    node: Any = manifest
    for step in path[:-1]:
        node = node[step]
    del node[path[-1]]
    return manifest


def _containers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    containers = manifest["spec"]["template"]["spec"]["containers"]
    assert isinstance(containers, list)
    return containers


# --- the central negative: absent from both sides is not a finding ------------------------


def test_a_protection_missing_from_both_sides_is_never_reported() -> None:
    """The property the whole module rests on.

    A Deployment that never had a liveness probe is not made worse by a change
    to its image tag. Reporting it would make every review a report about the
    workload's history, indistinguishable from the review of a change that just
    deleted one - and after two of those nobody reads the third.
    """
    before = _without(["spec", "template", "spec", "containers", 0, "livenessProbe"])
    after = copy.deepcopy(before)
    _containers(after)[0]["image"] = "checkout:v2"

    assessment = review(before, after)

    assert assessment.clean
    assert assessment.removed == []


def test_adding_a_protection_is_not_a_removal() -> None:
    """A difference is not a removal. Adding a probe and deleting one are the
    same inequality and opposite facts."""
    before = _without(["spec", "template", "spec", "containers", 0, "readinessProbe"])

    assessment = review(before, _deployment())

    assert assessment.clean


def test_an_added_object_removes_nothing_by_construction() -> None:
    assert review(None, _deployment()).clean


# --- what a removal looks like --------------------------------------------------------------


def test_deleting_a_probe_is_reported_with_what_it_exposes() -> None:
    """ "readinessProbe removed" is a fact; "traffic reaches the pod before it
    can serve it" is the reason somebody should care."""
    after = _without(["spec", "template", "spec", "containers", 0, "readinessProbe"])

    assessment = review(_deployment(), after)

    assert [protection.key for protection in assessment.removed] == ["readinessProbe"]
    assert "before it can serve it" in assessment.removed[0].exposes


def test_turning_on_privileged_is_a_removal_and_not_an_addition() -> None:
    """Modelled as the removal of the protection it cancels, so it travels
    through the same set difference rather than needing a second mechanism that
    would have to be kept in agreement with it."""
    after = _deployment()
    _containers(after)[0]["securityContext"] = {"privileged": True}

    keys = {protection.key for protection in review(_deployment(), after).removed}

    assert "unprivileged" in keys


def test_scaling_below_two_removes_redundancy() -> None:
    after = _deployment()
    after["spec"]["replicas"] = 1

    assessment = review(_deployment(), after)

    assert [protection.key for protection in assessment.removed] == ["redundancy"]
    assert (assessment.replicas_before, assessment.replicas_after) == (3, 1)


def test_an_empty_resources_block_is_not_a_limit() -> None:
    """`resources: {}` is how a limit is written when somebody meant to remove
    it, and it grants nothing."""
    after = _deployment()
    _containers(after)[0]["resources"] = {}

    keys = {protection.key for protection in review(_deployment(), after).removed}

    assert keys == {"cpu limit", "memory limit"}


def test_a_probe_written_as_an_empty_block_is_not_a_probe() -> None:
    """How somebody disables one in an overlay without deleting the key.

    This is what actually exercises the emptiness check. The earlier
    `resources: {}` test does not: the `or {}` chain resolves the empty dict
    before the check is reached, so the fixture could not express its claim -
    the plant that read presence instead of content passed it.
    """
    after = _deployment()
    _containers(after)[0]["livenessProbe"] = {}

    keys = {protection.key for protection in review(_deployment(), after).removed}

    assert keys == {"livenessProbe"}


def test_a_rollout_bound_of_zero_is_the_strictest_bound_and_not_an_absent_one() -> None:
    """`maxUnavailable: 0` means take nothing down. Reading zero as absent
    would treat the tightest rollout in the system as having no bound."""
    before = _deployment()
    before["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] = 0
    after = copy.deepcopy(before)
    del after["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"]

    keys = {protection.key for protection in review(before, after).removed}

    assert keys == {"bounded-rollout"}


def test_deleting_the_object_removes_everything_it_held() -> None:
    """Every pod-level protection, plus one entry per container rather than one
    per property the container carried.

    The collapse rule applies here too, and that is the coherent answer: a
    deleted Deployment did not lose a readiness probe, it lost the pods.
    """
    assessment = review(_deployment(), None)

    assert assessment.deleted
    assert not assessment.clean
    assert {protection.key for protection in assessment.removed} == {
        "container",
        "redundancy",
        "bounded-rollout",
        "spread",
        "pod-nonroot",
    }


def test_a_removed_container_reports_once_and_not_once_per_property() -> None:
    """ "unprivileged removed" is the wrong sentence for a container that no
    longer runs. It would bury the one fact that matters under five that do
    not, all of them technically true."""
    before = _deployment()
    _containers(before).append({"name": "authproxy", "livenessProbe": {"tcpSocket": {}}})

    assessment = review(before, _deployment())

    assert [(protection.key, protection.subject) for protection in assessment.removed] == [
        ("container", "authproxy")
    ]


def test_an_init_container_is_reviewed_too() -> None:
    """One that gains `privileged: true` runs as root on the node before the
    app container starts, and a reviewer walking only `spec.containers` would
    not see it."""
    before = _deployment()
    before["spec"]["template"]["spec"]["initContainers"] = [{"name": "migrate"}]
    after = copy.deepcopy(before)
    after["spec"]["template"]["spec"]["initContainers"][0]["securityContext"] = {"privileged": True}

    removed = review(before, after).removed

    assert [(protection.key, protection.subject) for protection in removed] == [
        ("unprivileged", "migrate")
    ]


# --- reach is a bound, not a count -----------------------------------------------------------


def test_a_daemonset_reaches_the_cluster_despite_being_namespaced() -> None:
    """It runs a pod on every node, so its namespace describes where the object
    lives rather than what the change can reach."""
    assert reach_of("DaemonSet") is Reach.CLUSTER
    assert reach_of("Deployment") is Reach.WORKLOAD


def test_a_configmap_reaches_its_namespace_because_its_consumers_are_unknown() -> None:
    """Which workloads mount it is not in the manifest. The namespace is the
    bound that can be stated without asking the cluster."""
    assert reach_of("ConfigMap") is Reach.NAMESPACE


def test_an_unrecognised_kind_reaches_no_further_than_a_workload() -> None:
    """The narrow answer for the unknown case. Guessing CLUSTER would make
    every custom resource a HIGH finding on the strength of not being on a
    list."""
    assert reach_of("WidgetSet") is Reach.WORKLOAD


def test_a_manifest_with_no_spec_holds_nothing_and_does_not_raise() -> None:
    """Manifests arrive from a diff, so half of them are malformed."""
    assert protections({"kind": "ConfigMap", "metadata": {"name": "flags"}}) == {}
    assert protections(None) == {}


# --- the agent ---------------------------------------------------------------------------------


async def _run(params: dict[str, Any]) -> Any:
    ctx = a_context()
    ctx.params = params
    return await Aegis().run(ctx)


async def test_a_change_that_removes_nothing_produces_no_findings() -> None:
    """A result, not a failure. Most changes are an image tag."""
    after = _deployment()
    _containers(after)[0]["image"] = "checkout:v2"

    outcome = await _run({"before": _deployment(), "after": after})

    assert outcome.status is AgentStatus.COMPLETE
    assert outcome.findings == []


async def test_a_removal_becomes_a_risk_finding_carrying_the_diff() -> None:
    after = _without(["spec", "template", "spec", "containers", 0, "livenessProbe"])

    outcome = await _run({"before": _deployment(), "after": after})

    (finding,) = outcome.findings
    assert finding.kind is FindingKind.RISK
    assert finding.agent == "aegis"
    assert "livenessProbe" in finding.title
    assert finding.subject is not None and finding.subject.name == "checkout"
    assert "stays Ready and broken" in finding.evidence[0].summary
    assert finding.evidence[0].payload.changed_fields == ["livenessProbe on api"]


async def test_severity_follows_reach_and_nothing_else() -> None:
    """A weighting over which protections matter more would be an opinion
    dressed as a measurement. Reach comes from the object model."""
    before = _deployment()
    before["kind"] = "DaemonSet"
    after = copy.deepcopy(before)
    del _containers(after)[0]["livenessProbe"]

    outcome = await _run({"before": before, "after": after})

    assert outcome.findings[0].severity is Severity.HIGH
    assert "cluster reach" in outcome.findings[0].title


async def test_several_changes_are_reviewed_independently() -> None:
    other = _deployment()
    other["metadata"] = {"name": "payments", "namespace": "shop"}
    stripped = copy.deepcopy(other)
    del stripped["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"]

    outcome = await _run(
        {
            "changes": [
                {"before": _deployment(), "after": _deployment()},
                {"before": other, "after": stripped},
            ]
        }
    )

    (finding,) = outcome.findings
    assert finding.subject is not None and finding.subject.name == "payments"


async def test_no_manifests_at_all_degrades_rather_than_reporting_clean() -> None:
    """An agent that returned no findings for a missing input would be
    indistinguishable from one that reviewed a safe change."""
    outcome = await _run({})

    assert outcome.status is AgentStatus.DEGRADED
    assert outcome.degraded_reason is not None
    assert "does not fetch them" in outcome.degraded_reason
    assert outcome.retryable is False


async def test_a_malformed_changes_list_degrades() -> None:
    outcome = await _run({"changes": "spec/deployment.yaml"})

    assert outcome.status is AgentStatus.DEGRADED
    assert outcome.degraded_reason is not None
    assert "not a list" in outcome.degraded_reason


async def test_an_entry_with_neither_side_degrades() -> None:
    outcome = await _run({"changes": [{"before": None, "after": None}]})

    assert outcome.status is AgentStatus.DEGRADED
    assert outcome.degraded_reason is not None
    assert "reviews as clean" in outcome.degraded_reason


# --- the toolset ----------------------------------------------------------------------------------


def test_aegis_declares_no_tools_and_implements_none() -> None:
    """A declared tool the agent never calls is an allowlist entry nobody uses,
    and the allowlist is what makes an agent's reach checkable by reading its
    manifest. Aegis previously declared four."""
    assert Aegis().manifest.tools == []
    assert IMPLEMENTATIONS == {}


async def test_aegis_calls_no_connector_during_a_real_review() -> None:
    """Asserted through a run rather than by reading the manifest, so the claim
    is about behaviour. The manifest could be widened tomorrow and this fails."""
    after = _without(["spec", "template", "spec", "containers", 0, "livenessProbe"])

    outcome = await _run({"before": _deployment(), "after": after})

    assert outcome.findings, "the review must have done something to prove it did it quietly"
    assert outcome.tool_calls == 0


@pytest.mark.parametrize("kind", ["ClusterRoleBinding", "ValidatingWebhookConfiguration"])
def test_cluster_scoped_kinds_are_recognised(kind: str) -> None:
    assert reach_of(kind) is Reach.CLUSTER
