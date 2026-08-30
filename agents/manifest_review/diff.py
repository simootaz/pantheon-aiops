"""What a manifest change takes away, and how far it reaches.

THE WHOLE MODULE IS ONE SET DIFFERENCE
----------------------------------------
`protections(before) - protections(after)`. Nothing here scans a manifest for
bad patterns, and that is the point rather than an implementation detail.

A reviewer that matched patterns on the AFTER state reports on the workload, not
on the change. Every review of an old Deployment without liveness probes would
say "no liveness probe" - true, unrelated to the diff, and indistinguishable
from the review of a change that just deleted one. After two of those nobody
reads the third.

So a protection missing from both sides never appears. A Deployment that never
had probes is not made worse by a change to its image tag, and Aegis says
nothing about it.

DIRECTION IS THE OTHER HALF
-----------------------------
A difference is not a removal. Adding a probe and deleting one are the same
`!=` and opposite facts, so the difference is taken in one direction only.
Things that read as additions - `privileged: true`, `allowPrivilegeEscalation:
true` - are modelled as the REMOVAL of the protection they cancel, so they
travel through the same mechanism instead of needing a second one that would
have to be kept in agreement with it.

REACH IS A BOUND, NOT A COUNT
-------------------------------
How many pods a change can affect is not in a manifest. `replicas` is, and it
is reported, but a DaemonSet's replica count is the node count and a ConfigMap's
consumers are whoever mounts it - neither is knowable here.

So reach is the narrowest bound statable from the manifest alone: workload,
namespace, or cluster. A DaemonSet is CLUSTER despite being namespaced, because
it runs on every node and its namespace says nothing about that.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Kinds whose blast radius is the whole cluster. `DaemonSet` is here despite
#: being namespaced: it runs a pod on every node, so its namespace describes
#: where the object lives rather than what the change can reach.
CLUSTER_SCOPED = frozenset(
    {
        "ClusterRole",
        "ClusterRoleBinding",
        "CustomResourceDefinition",
        "DaemonSet",
        "MutatingWebhookConfiguration",
        "Namespace",
        "PersistentVolume",
        "PriorityClass",
        "StorageClass",
        "ValidatingWebhookConfiguration",
    }
)

#: Kinds that reach beyond one workload without leaving the namespace. A
#: ConfigMap is here because which workloads mount it is not in the manifest -
#: the namespace is the bound that can be stated without asking the cluster.
NAMESPACE_SCOPED = frozenset(
    {
        "ConfigMap",
        "LimitRange",
        "NetworkPolicy",
        "PodDisruptionBudget",
        "ResourceQuota",
        "Role",
        "RoleBinding",
        "Secret",
        "Service",
        "ServiceAccount",
    }
)


class Reach(StrEnum):
    """How far a change can reach, bounded by what the manifest says."""

    WORKLOAD = "workload"
    NAMESPACE = "namespace"
    CLUSTER = "cluster"


@dataclass(frozen=True)
class Protection:
    """A safety property a manifest holds, and what its absence exposes.

    `exposes` is the half that makes a finding actionable. "readiness probe
    removed" is a fact; "traffic reaches the pod before it can serve it" is the
    reason somebody should care, and it is written once here rather than
    reconstructed at every call site.
    """

    key: str
    subject: str
    exposes: str

    @property
    def name(self) -> str:
        return f"{self.key} on {self.subject}" if self.subject else self.key


@dataclass(frozen=True)
class Review:
    """What one manifest change removes, and how far it reaches."""

    kind: str
    name: str
    namespace: str | None
    reach: Reach
    removed: list[Protection] = field(default_factory=list)
    replicas_before: int | None = None
    replicas_after: int | None = None
    deleted: bool = False

    @property
    def clean(self) -> bool:
        """Whether this change takes nothing away.

        A clean review is a result, not a failure to find anything - most
        changes are an image tag.
        """
        return not self.removed and not self.deleted


def reach_of(kind: str) -> Reach:
    if kind in CLUSTER_SCOPED:
        return Reach.CLUSTER
    if kind in NAMESPACE_SCOPED:
        return Reach.NAMESPACE
    return Reach.WORKLOAD


def _containers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Every container in a workload, init containers included.

    Init containers count. One that gains `privileged: true` runs as root on
    the node before the app container starts, and a reviewer that only walked
    `spec.containers` would not see it.
    """
    spec = manifest.get("spec") or {}
    pod = (spec.get("template") or {}).get("spec") or spec
    found: list[dict[str, Any]] = []
    for key in ("initContainers", "containers"):
        entries = pod.get(key)
        if isinstance(entries, list):
            found.extend(entry for entry in entries if isinstance(entry, dict))
    return found


def _truthy(value: Any) -> bool:
    """Whether a manifest value is set to something meaningful.

    `{}`, `[]` and `""` are how a field is written when somebody meant to
    disable it without deleting the key - a kustomize overlay setting
    `livenessProbe: {}` has no probe, and a reviewer reading presence would
    call that protected.

    Not used for numeric fields. `0` is falsy and meaningful, and the one
    numeric bound here is checked with `is not None` for exactly that reason.
    """
    return bool(value)


_PROBE_EXPOSES = {
    "livenessProbe": "a wedged process is never restarted, so the pod stays Ready and broken",
    "readinessProbe": "traffic reaches the pod before it can serve it, and during every restart",
    "startupProbe": "a slow-starting container is killed by the liveness probe before it is up",
}

_LIMIT_EXPOSES = {
    "cpu": "the container can starve every other pod on the node of CPU",
    "memory": "the container can consume the node's memory until the kernel picks a victim",
}


def protections(manifest: dict[str, Any] | None) -> dict[str, Protection]:
    """Every safety property this manifest currently holds, keyed.

    Keyed by a string rather than collected as a list, because the whole
    comparison is a set difference on these keys - two probes on two containers
    are two independent protections and must not collapse into one.

    A deleted object (`None`) holds nothing, which is what makes deleting a
    workload come out as the removal of everything it had.
    """
    if not manifest:
        return {}

    held: dict[str, Protection] = {}
    spec = manifest.get("spec") or {}

    replicas = spec.get("replicas")
    if isinstance(replicas, int) and replicas > 1:
        held["redundancy"] = Protection(
            key="redundancy",
            subject="",
            exposes=(
                f"{replicas} replicas become one or none, so the workload has no "
                "surviving instance while a pod restarts"
            ),
        )

    # `is not None`, not truthiness. `maxUnavailable: 0` is the STRICTEST bound
    # there is - take nothing down - and reading zero as absent would treat the
    # tightest rollout in the system as having no bound at all.
    #
    # Only the removal of the bound is detected, not its widening: 1 -> 5 keeps
    # the key and passes silently. Catching that needs the value in the key, and
    # then a tightening (5 -> 1) reports as a removal too - a reviewer that
    # flags making a rollout safer is worse than one that stays quiet.
    rolling = (spec.get("strategy") or {}).get("rollingUpdate") or {}
    if rolling.get("maxUnavailable") is not None:
        held["bounded-rollout"] = Protection(
            key="bounded-rollout",
            subject="",
            exposes="a rollout can take every pod down at once instead of a bounded share",
        )

    if _truthy(((spec.get("template") or {}).get("spec") or {}).get("topologySpreadConstraints")):
        held["spread"] = Protection(
            key="spread",
            subject="",
            exposes="every replica can be scheduled onto one node, so one node failure is total",
        )

    pod_security = ((spec.get("template") or {}).get("spec") or {}).get("securityContext") or {}
    if pod_security.get("runAsNonRoot") is True:
        held["pod-nonroot"] = Protection(
            key="pod-nonroot",
            subject="",
            exposes="pods may run as root, so a container escape starts with root on the node",
        )

    for container in _containers(manifest):
        name = str(container.get("name") or "unnamed")
        held[f"container:{name}"] = Protection(
            key="container",
            subject=name,
            exposes=(
                "the container is gone from the workload. Whatever it did - proxying "
                "auth, shipping logs, terminating TLS - is not happening after this"
            ),
        )

        for probe in ("livenessProbe", "readinessProbe", "startupProbe"):
            if _truthy(container.get(probe)):
                held[f"{probe}:{name}"] = Protection(
                    key=probe,
                    subject=name,
                    exposes=_PROBE_EXPOSES[probe],
                )

        limits = (container.get("resources") or {}).get("limits") or {}
        for resource in ("cpu", "memory"):
            if _truthy(limits.get(resource)):
                held[f"limit.{resource}:{name}"] = Protection(
                    key=f"{resource} limit",
                    subject=name,
                    exposes=_LIMIT_EXPOSES[resource],
                )

        security = container.get("securityContext") or {}
        if not security.get("privileged"):
            held[f"unprivileged:{name}"] = Protection(
                key="unprivileged",
                subject=name,
                exposes=(
                    "the container runs privileged, with the host's devices and "
                    "capabilities - a compromise is a node compromise"
                ),
            )
        if not security.get("allowPrivilegeEscalation"):
            held[f"no-escalation:{name}"] = Protection(
                key="no-privilege-escalation",
                subject=name,
                exposes=(
                    "a process inside the container can gain more privileges than it started with"
                ),
            )
        if security.get("readOnlyRootFilesystem") is True:
            held[f"readonly-root:{name}"] = Protection(
                key="read-only root filesystem",
                subject=name,
                exposes=(
                    "the container image can be modified at runtime, so what ran "
                    "is not what was built"
                ),
            )

    return held


def review(before: dict[str, Any] | None, after: dict[str, Any] | None) -> Review:
    """What changing `before` into `after` takes away.

    One direction. A difference is not a removal: adding a probe and deleting
    one are the same inequality and opposite facts.
    """
    present = after or before or {}
    metadata = present.get("metadata") or {}
    kind = str(present.get("kind") or "Unknown")

    held_before = protections(before)
    held_after = protections(after)
    lost = [held_before[key] for key in held_before.keys() - held_after.keys()]

    # A container that is gone reports once. Its probes and limits went with it,
    # and "unprivileged removed" is the wrong sentence for a container that no
    # longer runs - it would bury the one fact that matters under five that do
    # not, all of them technically true.
    gone = {protection.subject for protection in lost if protection.key == "container"}
    lost = [
        protection
        for protection in lost
        if protection.key == "container" or protection.subject not in gone
    ]

    return Review(
        kind=kind,
        name=str(metadata.get("name") or "unnamed"),
        namespace=metadata.get("namespace"),
        reach=reach_of(kind),
        removed=sorted(lost, key=lambda protection: (protection.subject, protection.key)),
        replicas_before=_replicas(before),
        replicas_after=_replicas(after),
        deleted=before is not None and after is None,
    )


def _replicas(manifest: dict[str, Any] | None) -> int | None:
    """The declared replica count, or `None` when the manifest does not say.

    `None` and `0` are different. A manifest with no `replicas` field is one
    Kubernetes will default, and reporting that as zero would say the change
    scaled something to nothing.
    """
    if not manifest:
        return None
    replicas = (manifest.get("spec") or {}).get("replicas")
    return replicas if isinstance(replicas, int) else None
