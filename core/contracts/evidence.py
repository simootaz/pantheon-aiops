"""Evidence: one observed datum an agent collected.

A metric window, a log cluster, a manifest diff, a Kubernetes event, a pipeline
run. Evidence is the raw material a Finding is built from, and the reason a
Finding can be argued with rather than merely believed.

PER-KIND PAYLOADS ARE A DISCRIMINATED UNION
-------------------------------------------
Phase 0 carried `payload: dict[str, Any]` with a TODO. That shape cannot be
validated, cannot be generated into a useful Go or TypeScript type, and pushes
every consumer into defensive key-checking. Each kind now has its own model,
selected by a string discriminator.

The discriminator is a plain string `Literal`, not an enum member. `events.py`
established that: `const` in JSON Schema is what every downstream generator
reads consistently, whereas a nullable enum breaks Go generation outright (see
codegen/gen_go.sh).

`EvidenceKind` remains the queryable vocabulary, and
`tests/unit/test_contracts.py` asserts it stays exactly in step with the union -
a kind with no payload model, or a payload model with no kind, is a bug that
would otherwise surface as a runtime `KeyError` months later.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from core.contracts.base import ContractModel


class EvidenceKind(StrEnum):
    """What sort of observation this Evidence carries.

    Every member has exactly one payload model below, and every payload model
    has exactly one member here. Guarded by test.
    """

    METRIC_WINDOW = "metric_window"
    LOG_CLUSTER = "log_cluster"
    MANIFEST_DIFF = "manifest_diff"
    K8S_EVENT = "k8s_event"
    PIPELINE_RUN = "pipeline_run"


class ResourceRef(ContractModel):
    """What a piece of Evidence is about.

    Deliberately not Kubernetes-shaped: a pipeline and a database are subjects
    too, and forcing them into `namespace/kind/name` would be a lie that costs
    an adapter at every call site.
    """

    kind: str = Field(description="e.g. 'deployment', 'pipeline', 'node'.")
    name: str
    namespace: str | None = Field(default=None, description="Where applicable.")
    cluster: str | None = None


class EvidenceSource(ContractModel):
    """Where a piece of Evidence came from, so a human can go and look."""

    connector: str = Field(description="Connector that produced it, e.g. 'prometheus'.")
    query: str | None = Field(default=None, description="Query that produced it, verbatim.")
    collected_at: datetime | None = Field(
        default=None, description="When the connector ran, as distinct from what it observed."
    )


class MetricSample(ContractModel):
    """One point on a series."""

    at: datetime
    value: float


class BaselineEstimator(StrEnum):
    """How a baseline's centre and scale were computed.

    A closed set rather than free text, and deliberately so: an estimator field
    typed `str` is where `median_mad`, `MAD` and `robust` all appear within a
    month, and nothing can compare two Findings after that. Every payload
    carrying a baseline must name one - guarded by test.
    """

    #: median for centre, 1.4826 x MAD for scale. Robust to its own fault: MAD
    #: has a 50% breakdown point, so a deviation occupying under half the window
    #: leaves the estimate intact. Mean and standard deviation do not - a spike
    #: inflates the scale and hides itself.
    MEDIAN_MAD = "median_mad"

    #: arithmetic mean and standard deviation. Present because it is what a
    #: reader assumes unless told otherwise, and because a series known to carry
    #: no contamination is cheaper to summarise this way. Not used for
    #: detection.
    MEAN_STDDEV = "mean_stddev"

    #: no baseline was computed - the payload carries samples only. An explicit
    #: member rather than a null: `Evidence | None` on an enum breaks Go
    #: codegen with a duplicate UnmarshalJSON, which
    #: `test_schema_contains_no_nullable_enum` forbids. It reads better too,
    #: since "no baseline" is a state the producer chose rather than a field
    #: someone forgot.
    NOT_APPLICABLE = "not_applicable"


class MetricWindowPayload(ContractModel):
    """A slice of a time series, with the baseline it is being judged against.

    `deviation_sigma` is carried rather than recomputed downstream so that the
    dashboard, the verdict and the audit trail all agree on how unusual this
    was - recomputing invites three different answers.

    `scale_floor_engaged` says whether the number can be read as a measurement
    at all. When every sample in a window agrees, MAD is exactly zero and the
    scale falls back to a floor - after which `deviation_sigma` is a property of
    the floor, not of the distribution. `disk_ratio` over three nodes produced
    1599.63 on a *clean* baseline and 1585.74 as a *signal*: both were the floor
    speaking. A number whose provenance is the floor must not be
    indistinguishable from one whose provenance is the data.

    The baseline is `centre` and `scale` rather than `mean` and `stddev`, and
    the estimator is named. Detection here is median/MAD, and writing a median
    into a field called `baseline_mean` is a number that looks meaningful and is
    not - the reader would compare it against a mean from somewhere else. The
    previous fields were removed rather than kept alongside: two estimators side
    by side invites exactly that comparison, and the one on display would be the
    one that breaks under contamination.
    """

    kind: Literal["metric_window"] = "metric_window"
    metric: str = Field(description="Metric name, e.g. 'container_memory_working_set_bytes'.")
    unit: str = Field(default="", description="e.g. 'bytes', 'seconds', 'requests/s'.")
    samples: list[MetricSample] = Field(default_factory=list)
    estimator: BaselineEstimator = Field(
        default=BaselineEstimator.NOT_APPLICABLE,
        description="How centre and scale were computed. Must be stated if either is set.",
    )
    baseline_centre: float | None = Field(
        default=None, description="Middle of the baseline, by `estimator`."
    )
    baseline_scale: float | None = Field(
        default=None, ge=0.0, description="Spread of the baseline, by `estimator`."
    )
    deviation_sigma: float | None = Field(
        default=None, description="Deviations from centre, in units of scale, signed."
    )
    scale_floor_engaged: bool = Field(
        default=False,
        description=(
            "The scale collapsed and a floor was substituted, so `deviation_sigma` is "
            "determined by the floor rather than by the data's own spread."
        ),
    )
    window_seconds: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _a_baseline_names_its_estimator(self) -> MetricWindowPayload:
        """Centre or scale without an estimator is an uninterpretable number."""
        has_baseline = self.baseline_centre is not None or self.baseline_scale is not None
        if has_baseline and self.estimator is BaselineEstimator.NOT_APPLICABLE:
            raise ValueError(
                "baseline_centre/baseline_scale set without an estimator: the numbers "
                "cannot be compared against anything without knowing how they were computed"
            )
        return self


class LogClusterPayload(ContractModel):
    """A group of log lines sharing a template, plus how surprising it is."""

    kind: Literal["log_cluster"] = "log_cluster"
    template: str = Field(description="Normalised line with variables masked.")
    sample_lines: list[str] = Field(
        default_factory=list, description="Verbatim examples. Redacted before emission."
    )
    occurrences: int = Field(default=0, ge=0)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    novelty: float | None = Field(
        default=None, ge=0.0, le=1.0, description="1.0 means never seen before this window."
    )


class ManifestDiffPayload(ContractModel):
    """A change to a manifest or IaC definition, and what it touches."""

    kind: Literal["manifest_diff"] = "manifest_diff"
    target: ResourceRef
    diff: str = Field(description="Unified diff.")
    changed_fields: list[str] = Field(default_factory=list)
    revision_before: str | None = None
    revision_after: str | None = None


class K8sEventPayload(ContractModel):
    """A Kubernetes event, which is often the shortest path to the answer."""

    kind: Literal["k8s_event"] = "k8s_event"
    target: ResourceRef
    reason: str = Field(description="e.g. 'OOMKilling', 'Unhealthy', 'FailedScheduling'.")
    message: str
    event_type: str = Field(default="Warning", description="'Normal' or 'Warning'.")
    count: int = Field(default=1, ge=1)
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class PipelineRunPayload(ContractModel):
    """One CI pipeline run and the jobs that failed in it."""

    kind: Literal["pipeline_run"] = "pipeline_run"
    pipeline_id: str
    project: str
    ref: str = Field(description="Branch or tag.")
    status: str = Field(description="e.g. 'failed', 'success'.")
    failed_jobs: list[str] = Field(default_factory=list)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    commit_sha: str | None = None


EvidencePayload = Annotated[
    MetricWindowPayload
    | LogClusterPayload
    | ManifestDiffPayload
    | K8sEventPayload
    | PipelineRunPayload,
    Field(discriminator="kind"),
]
"""Discriminated union of everything Evidence can carry."""


class Evidence(ContractModel):
    """A single observation, attributable to one connector at one moment."""

    id: UUID
    source: EvidenceSource
    observed_at: datetime = Field(description="When the thing happened, not when it was fetched.")
    summary: str = Field(description="One line a human can read without expanding the payload.")
    subject: ResourceRef | None = Field(
        default=None, description="What this is about, when it is about one thing."
    )
    payload: EvidencePayload

    @property
    def kind(self) -> EvidenceKind:
        """The kind, read off the payload rather than stored twice.

        Storing it alongside the payload would create an invariant nobody
        enforces, and eventually a record whose two halves disagree.
        """
        return EvidenceKind(self.payload.kind)


# TODO: Phase 2 - add a provenance chain linking derived Evidence to its source
