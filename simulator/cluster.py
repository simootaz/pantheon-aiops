"""The fake cluster: three nodes, twelve pods.

Metrics and logs both describe *these* entities. A simulator whose log stream
mentions pods its metric stream has never heard of teaches an agent to correlate
things that do not correlate, which is worse than no simulator at all.

Deliberately small and fixed. Randomising the topology per run would make a
failed scenario impossible to reproduce, and reproducibility is the point.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from dataclasses import dataclass

CLUSTER = "sim-cluster"
NAMESPACE = "production"


@dataclass(frozen=True, slots=True)
class Node:
    """A worker node, with the capacity a scenario can saturate."""

    name: str
    cpu_cores: float
    memory_bytes: int
    disk_bytes: int


@dataclass(frozen=True, slots=True)
class Pod:
    """A workload on a node.

    `base_rps` and the resource baselines are what "normal" looks like. A
    scenario perturbs them; it does not replace them, so an anomaly stays
    visible against the pod's own history rather than against a global constant.
    """

    name: str
    node: str
    service: str
    base_rps: float
    base_cpu_cores: float
    base_memory_bytes: int
    base_latency_seconds: float


GIB = 1024**3

NODES: tuple[Node, ...] = (
    Node(name="node-a", cpu_cores=8.0, memory_bytes=32 * GIB, disk_bytes=200 * GIB),
    Node(name="node-b", cpu_cores=8.0, memory_bytes=32 * GIB, disk_bytes=200 * GIB),
    Node(name="node-c", cpu_cores=4.0, memory_bytes=16 * GIB, disk_bytes=100 * GIB),
)

#: Twelve pods across four services. `checkout` is the busiest, which is why
#: most scenarios pick on it - a fault in a quiet workload is easy to spot and
#: therefore a weak test.
PODS: tuple[Pod, ...] = (
    Pod("checkout-7d4f9b-a1", "node-a", "checkout", 180.0, 0.85, 1200 * 1024**2, 0.120),
    Pod("checkout-7d4f9b-b2", "node-a", "checkout", 175.0, 0.82, 1180 * 1024**2, 0.118),
    Pod("checkout-7d4f9b-c3", "node-b", "checkout", 178.0, 0.84, 1210 * 1024**2, 0.122),
    Pod("payments-5c8e2a-a1", "node-a", "payments", 95.0, 0.60, 900 * 1024**2, 0.085),
    Pod("payments-5c8e2a-b2", "node-b", "payments", 92.0, 0.58, 890 * 1024**2, 0.087),
    Pod("catalog-9a1d3e-a1", "node-b", "catalog", 240.0, 0.45, 640 * 1024**2, 0.032),
    Pod("catalog-9a1d3e-b2", "node-b", "catalog", 238.0, 0.44, 630 * 1024**2, 0.031),
    Pod("catalog-9a1d3e-c3", "node-c", "catalog", 235.0, 0.46, 650 * 1024**2, 0.033),
    Pod("search-2f6b8c-a1", "node-c", "search", 60.0, 1.10, 2400 * 1024**2, 0.210),
    Pod("search-2f6b8c-b2", "node-c", "search", 58.0, 1.05, 2350 * 1024**2, 0.205),
    Pod("notifier-4e7a1f-a1", "node-a", "notifier", 25.0, 0.20, 320 * 1024**2, 0.045),
    Pod("notifier-4e7a1f-b2", "node-c", "notifier", 24.0, 0.19, 315 * 1024**2, 0.046),
)

PODS_BY_NAME: dict[str, Pod] = {pod.name: pod for pod in PODS}
NODES_BY_NAME: dict[str, Node] = {node.name: node for node in NODES}
SERVICES: tuple[str, ...] = tuple(dict.fromkeys(pod.service for pod in PODS))


def pods_for(selector: str) -> tuple[Pod, ...]:
    """Resolve a scenario's target selector to pods.

    Accepts a service name (`checkout`), a node name (`node-c`), an exact pod
    name, or `*`. Anything else raises rather than silently matching nothing —
    a scenario that targets a typo would otherwise inject a fault into an empty
    set and still report success.
    """
    if selector == "*":
        return PODS
    if selector in SERVICES:
        return tuple(pod for pod in PODS if pod.service == selector)
    if selector in NODES_BY_NAME:
        return tuple(pod for pod in PODS if pod.node == selector)
    if selector in PODS_BY_NAME:
        return (PODS_BY_NAME[selector],)
    raise KeyError(
        f"target {selector!r} matches no service, node or pod. "
        f"services={list(SERVICES)} nodes={list(NODES_BY_NAME)}"
    )
