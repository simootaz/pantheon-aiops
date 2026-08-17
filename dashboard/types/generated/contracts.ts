/* eslint-disable */
/**
 * Generated from core/contracts/ by codegen/gen_ts.sh. DO NOT EDIT BY HAND.
 *
 * Source of truth: core/contracts/ (Pydantic v2), via
 * core/contracts/export/pantheon.schema.json. Regenerate with: make codegen
 */

export type A2UiVersion = string;
export type CatalogId = string;
/**
 * The closed allowlist of A2UI components Pantheon will render.
 *
 * A subset of A2UI's basic catalog. Agent-generated UI is untrusted data, so
 * the catalog is chosen for what it *cannot* be abused to do.
 *
 * ``Image`` is present but **cannot take a URL**. It takes an ArtifactRef: an
 * object key for an artifact Pantheon itself produced and stored. The agent
 * cannot express an arbitrary destination, so there is nothing to filter.
 *
 * Deliberately excluded, with reasons:
 *
 * - ``Video``, ``AudioPlayer`` - nothing needs them yet. They would follow the
 *   same ArtifactRef pattern when something does; the allowlist grows on
 *   demand, never speculatively.
 * - ``Modal`` - an agent that can force a modal can overlay a convincing fake
 *   credential prompt. Credential requests travel one path only, through
 *   Cerberus.
 * - ``Tabs``, ``Slider`` - no current use.
 */
export type A2UIComponentType =
  | "Row"
  | "Column"
  | "Card"
  | "List"
  | "Text"
  | "Image"
  | "Icon"
  | "Divider"
  | "TextField"
  | "CheckBox"
  | "ChoicePicker"
  | "DateTimeInput"
  | "Button";
/**
 * Every component the renderer accepts.
 */
export type Components = A2UIComponentType[];
export type A2UiVersion1 = string;
/**
 * Set by the orchestrator. An agent cannot claim another identity.
 */
export type AgentDisplayName = string;
export type CatalogId1 = string;
/**
 * Server-dispatched action name, from the catalog.
 */
export type EventName = string | null;
/**
 * Client function name, from the catalog. Never code.
 */
export type FunctionCall = string | null;
/**
 * Accessible description. Rendered, not fetched.
 */
export type AltText = string;
/**
 * Resolution rejects a reference from a different investigation.
 */
export type InvestigationId = string;
/**
 * Object key within Pantheon's own artifact bucket.
 */
export type Key = string;
/**
 * What an artifact is. Only images are renderable today.
 */
export type ArtifactKind = "image";
/**
 * Child component ids.
 */
export type Children = string[];
/**
 * The closed allowlist of A2UI components Pantheon will render.
 *
 * A subset of A2UI's basic catalog. Agent-generated UI is untrusted data, so
 * the catalog is chosen for what it *cannot* be abused to do.
 *
 * ``Image`` is present but **cannot take a URL**. It takes an ArtifactRef: an
 * object key for an artifact Pantheon itself produced and stored. The agent
 * cannot express an arbitrary destination, so there is nothing to filter.
 *
 * Deliberately excluded, with reasons:
 *
 * - ``Video``, ``AudioPlayer`` - nothing needs them yet. They would follow the
 *   same ArtifactRef pattern when something does; the allowlist grows on
 *   demand, never speculatively.
 * - ``Modal`` - an agent that can force a modal can overlay a convincing fake
 *   credential prompt. Credential requests travel one path only, through
 *   Cerberus.
 * - ``Tabs``, ``Slider`` - no current use.
 */
export type A2UIComponentType1 =
  | "Row"
  | "Column"
  | "Card"
  | "List"
  | "Text"
  | "Image"
  | "Icon"
  | "Divider"
  | "TextField"
  | "CheckBox"
  | "ChoicePicker"
  | "DateTimeInput"
  | "Button";
/**
 * RFC 6901 JSON Pointer into the surface data model.
 */
export type DataPath = string | null;
/**
 * Unique within its surface.
 */
export type Id = string;
/**
 * Input label, where the type takes one.
 */
export type Label = string | null;
/**
 * Display text, where the type takes one.
 */
export type Text = string | null;
export type Components1 = A2UIComponent[];
/**
 * Set by the orchestrator. Never agent-supplied.
 */
export type IconUrl = string | null;
export type Id1 = string;
export type InvestigationId1 = string | null;
/**
 * What a Pantheon-authored surface is for.
 *
 * Every surface Pantheon emits has a declared purpose, so the renderer can
 * apply the right handling - notably that only APPROVAL and ACCESS_REQUEST may
 * collect a decision, and both are bound to their existing backend paths.
 */
export type A2UISurfaceKind = "approval" | "access_request" | "report" | "notice";
/**
 * Id of the root component.
 */
export type Root = string;
/**
 * Read and write are separate grants.
 *
 * Approving read never implies write, mirroring the connector split between
 * internal/readonly and internal/write.
 *
 * NOT_APPLICABLE exists for audit entries that concern no single access -
 * break-glass and rotation, for instance. It is meaningful only on AuditEntry;
 * a Grant, Lease or AccessRequest carrying it is invalid, and Phase 3
 * validation rejects it.
 *
 * It is also why AuditEntry.action is not simply nullable: a nullable enum
 * emits `anyOf: [$ref, null]`, which go-jsonschema v0.24.1 turns into two
 * conflicting UnmarshalJSON methods on the same Go type. Stating "not
 * applicable" explicitly is clearer than an implicit null convention anyway.
 */
export type CredentialAction = "read" | "write" | "not_applicable";
export type Agent = string;
/**
 * Opaque identifier of the stored credential.
 */
export type Id2 = string;
/**
 * Human-readable label, e.g. 'prod-postgres'.
 */
export type Name = string;
/**
 * e.g. 'prod'. Drives defaults.
 */
export type Environment = string | null;
/**
 * Host or cluster, e.g. 'db-01'.
 */
export type Server = string | null;
/**
 * Logical service, e.g. 'checkout'.
 */
export type Service = string | null;
/**
 * What kind of credential this is. Governs how the store handles it.
 */
export type CredentialType = "database" | "ssh" | "kubeconfig" | "http_auth" | "cloud_key" | "tls" | "key_value";
export type Id3 = string;
export type InvestigationId2 = string;
/**
 * The hypothesis this access would test, in the agent's own words.
 */
export type Reason = string;
export type RequestedAt = string;
/**
 * How long the agent expects to need it.
 */
export type RequestedTtlSeconds = number;
/**
 * Where an Action sits in the human-in-the-loop gate.
 */
export type ApprovalState = "not_required" | "pending" | "approved" | "rejected" | "expired";
/**
 * How much can break if this Action is wrong.
 */
export type BlastRadius = "none" | "single_workload" | "namespace" | "cluster" | "multi_cluster";
/**
 * Dry run until explicitly cleared.
 */
export type DryRun = boolean;
/**
 * What actually happened, as distinct from what was permitted.
 */
export type ExecutionState = "proposed" | "dry_run" | "executing" | "succeeded" | "failed" | "rolled_back" | "skipped";
export type Id4 = string;
/**
 * What it does, e.g. 'rollout_restart', 'scale'.
 */
export type Operation = string;
export type ProposedAt = string;
/**
 * Agent codename, or 'zeus'.
 */
export type ProposedBy = string;
/**
 * Why this Action was proposed, in terms of the Verdict.
 */
export type Reason1 = string;
export type At = string;
/**
 * Which connector executed it.
 */
export type Connector = string;
/**
 * Human-readable outcome. Never a credential.
 */
export type Detail = string;
/**
 * The lease it was executed under.
 */
export type LeaseId = string | null;
/**
 * What actually happened, as distinct from what was permitted.
 */
export type ExecutionState1 = "proposed" | "dry_run" | "executing" | "succeeded" | "failed" | "rolled_back" | "skipped";
/**
 * Append-only execution history.
 */
export type Receipts = ActionReceipt[];
/**
 * How to undo it. Required for anything wider than a single workload.
 */
export type Rollback = string | null;
export type Cluster = string | null;
/**
 * e.g. 'deployment', 'pipeline', 'node'.
 */
export type Kind = string;
export type Name1 = string;
/**
 * Where applicable.
 */
export type Namespace = string | null;
export type MaxSeconds = number;
export type MaxTokens = number;
export type MaxToolCalls = number;
export type Description = string;
/**
 * Stable identifier, e.g. 'detect_metric_anomaly'.
 */
export type Name2 = string;
export type Capabilities = AgentCapability[];
/**
 * Mythological name, e.g. 'argus'.
 */
export type Codename = string;
export type Description1 = string;
/**
 * Folder under agents/, e.g. 'anomaly'.
 */
export type Domain = string;
/**
 * Connector tools this agent may call.
 */
export type Tools = string[];
/**
 * Read and write are separate grants.
 *
 * Approving read never implies write, mirroring the connector split between
 * internal/readonly and internal/write.
 *
 * NOT_APPLICABLE exists for audit entries that concern no single access -
 * break-glass and rotation, for instance. It is meaningful only on AuditEntry;
 * a Grant, Lease or AccessRequest carrying it is invalid, and Phase 3
 * validation rejects it.
 *
 * It is also why AuditEntry.action is not simply nullable: a nullable enum
 * emits `anyOf: [$ref, null]`, which go-jsonschema v0.24.1 turns into two
 * conflicting UnmarshalJSON methods on the same Go type. Stating "not
 * applicable" explicitly is clearer than an implicit null convention anyway.
 */
export type CredentialAction1 = "read" | "write" | "not_applicable";
/**
 * Agent codename, user, or 'system'.
 */
export type Actor = string;
export type At1 = string;
/**
 * Human-readable context. Never a credential.
 */
export type Detail1 = string;
/**
 * Everything Cerberus records. The log is append-only.
 */
export type AuditEvent =
  | "requested"
  | "granted"
  | "denied"
  | "approval_requested"
  | "lease_minted"
  | "lease_used"
  | "lease_renewed"
  | "lease_expired"
  | "lease_revoked"
  | "grant_revoked"
  | "break_glass"
  | "rotated";
export type Id5 = string;
export type InvestigationId3 = string | null;
export type LeaseId1 = string | null;
export type EmittedAt = string;
export type Event =
  | InvestigationStartedEvent
  | InvestigationCompletedEvent
  | StepStartedEvent
  | StepFinishedEvent
  | FindingProducedEvent
  | HypothesisProposedEvent
  | VerdictReadyEvent
  | ApprovalRequestedEvent
  | AccessRequestedEvent
  | LeaseExpiredEvent
  | BreakGlassEvent;
export type InvestigationId4 = string;
export type Type = "investigation_started";
export type InvestigationId5 = string;
/**
 * True when any agent reported DEGRADED.
 */
export type Partial = boolean;
/**
 * The terminal InvestigationState value.
 */
export type State = string;
export type Type1 = "investigation_completed";
export type Agent1 = string;
export type InvestigationId6 = string;
export type Type2 = "step_started";
export type Agent2 = string;
export type FindingCount = number;
export type InvestigationId7 = string;
export type Type3 = "step_finished";
/**
 * Codename of the agent that produced it, e.g. 'argus'.
 */
export type Agent3 = string;
/**
 * The agent's own confidence, 0 to 1.
 */
export type Confidence = number;
export type DetectedAt = string;
export type Id6 = string;
/**
 * When the thing happened, not when it was fetched.
 */
export type ObservedAt = string;
export type Payload =
  MetricWindowPayload | LogClusterPayload | ManifestDiffPayload | K8SEventPayload | PipelineRunPayload;
export type BaselineMean = number | null;
export type BaselineStddev = number | null;
/**
 * How many standard deviations from baseline, signed.
 */
export type DeviationSigma = number | null;
export type Kind1 = "metric_window";
/**
 * Metric name, e.g. 'container_memory_working_set_bytes'.
 */
export type Metric = string;
export type At2 = string;
export type Value = number;
export type Samples = MetricSample[];
/**
 * e.g. 'bytes', 'seconds', 'requests/s'.
 */
export type Unit = string;
export type WindowSeconds = number;
export type FirstSeen = string | null;
export type Kind2 = "log_cluster";
export type LastSeen = string | null;
/**
 * 1.0 means never seen before this window.
 */
export type Novelty = number | null;
export type Occurrences = number;
/**
 * Verbatim examples. Redacted before emission.
 */
export type SampleLines = string[];
/**
 * Normalised line with variables masked.
 */
export type Template = string;
export type ChangedFields = string[];
/**
 * Unified diff.
 */
export type Diff = string;
export type Kind3 = "manifest_diff";
export type RevisionAfter = string | null;
export type RevisionBefore = string | null;
export type Count = number;
/**
 * 'Normal' or 'Warning'.
 */
export type EventType = string;
export type FirstSeen1 = string | null;
export type Kind4 = "k8s_event";
export type LastSeen1 = string | null;
export type Message = string;
/**
 * e.g. 'OOMKilling', 'Unhealthy', 'FailedScheduling'.
 */
export type Reason2 = string;
export type CommitSha = string | null;
export type DurationSeconds = number | null;
export type FailedJobs = string[];
export type Kind5 = "pipeline_run";
export type PipelineId = string;
export type Project = string;
/**
 * Branch or tag.
 */
export type Ref = string;
/**
 * e.g. 'failed', 'success'.
 */
export type Status = string;
/**
 * When the connector ran, as distinct from what it observed.
 */
export type CollectedAt = string | null;
/**
 * Connector that produced it, e.g. 'prometheus'.
 */
export type Connector1 = string;
/**
 * Query that produced it, verbatim.
 */
export type Query = string | null;
/**
 * One line a human can read without expanding the payload.
 */
export type Summary = string;
/**
 * Evidence supporting the claim. A Finding with none is inadmissible.
 */
export type Evidence = Evidence1[];
export type Id7 = string;
/**
 * What sort of claim this is.
 *
 * DEGRADED is the important one: it is how an agent reports that it could not
 * do its job - a lease expired, a connector was unreachable, a budget ran out.
 * Making it a Finding rather than a silent absence is what keeps a partial
 * investigation visibly partial.
 */
export type FindingKind = "observation" | "anomaly" | "correlation" | "risk" | "degraded";
/**
 * Why the Evidence supports the claim.
 */
export type Rationale = string | null;
/**
 * How much a Finding should worry the on-call engineer.
 */
export type Severity = "info" | "low" | "medium" | "high" | "critical";
/**
 * Free-form, for grouping.
 */
export type Tags = string[];
/**
 * One line, specific enough to act on.
 */
export type Title = string;
export type WindowEnd = string | null;
/**
 * Start of the period this claim is about.
 */
export type WindowStart = string | null;
export type InvestigationId8 = string;
export type Type4 = "finding_produced";
/**
 * The closed vocabulary shared by agents, verdicts and scenario ground truth.
 *
 * Adding a member is a deliberate act: it widens what an agent may conclude
 * and what a scenario may assert. `UNKNOWN` exists so that "we do not know" is
 * a statable conclusion rather than an absent one - an investigation that
 * cannot say it will invent something instead.
 */
export type RootCauseCategory =
  | "memory_leak"
  | "resource_contention"
  | "bad_deployment"
  | "config_error"
  | "disk_exhaustion"
  | "capacity_saturation"
  | "dependency_failure"
  | "network_partition"
  | "flaky_test"
  | "data_corruption"
  | "external_incident"
  | "unknown";
export type Confidence1 = number;
/**
 * Recorded deliberately. A hypothesis with none listed has usually not been tested, rather than survived testing.
 */
export type ContradictingFindingIds = string[];
export type Id8 = string;
/**
 * Agent codename, or 'zeus' for an aggregated one.
 */
export type ProposedBy1 = string;
/**
 * Why the evidence implies this.
 */
export type Reasoning = string | null;
/**
 * One sentence a human can act on, e.g. 'checkout leaks connections under retry storms, exhausting the pool'.
 */
export type Statement = string;
/**
 * Where a hypothesis stands once the evidence is in.
 */
export type HypothesisStatus = "proposed" | "supported" | "refuted" | "inconclusive";
/**
 * What it is about, e.g. 'deployment/checkout'.
 */
export type Subject = string | null;
export type SupportingFindingIds = string[];
export type InvestigationId9 = string;
export type Type5 = "hypothesis_proposed";
export type InvestigationId10 = string;
export type Type6 = "verdict_ready";
/**
 * Confidence in the leading hypothesis.
 */
export type Confidence2 = number;
export type ContributingFindings = Finding[];
export type DecidedAt = string;
/**
 * Ranked most-likely first. Empty means no explanation was reached, which is a legitimate outcome and must not be dressed up as one.
 */
export type Hypotheses = RootCauseHypothesis[];
export type Id9 = string;
export type InvestigationId11 = string;
/**
 * True when an agent reported DEGRADED, so the conclusion rests on incomplete evidence. Surfaced to the reader rather than buried.
 */
export type Partial1 = boolean;
export type RecommendedActions = Action[];
/**
 * What happened, in one paragraph, for a human.
 */
export type Summary1 = string;
export type InvestigationId12 = string;
export type Type7 = "approval_requested";
export type InvestigationId13 = string;
export type Type8 = "access_requested";
export type Agent4 = string;
export type InvestigationId14 = string;
export type LeaseId2 = string;
export type Reason3 = "expired" | "revoked";
export type Type9 = "lease_expired";
export type InvokedBy = string;
export type LeasesRevoked = number;
export type Reason4 = string;
export type Type10 = "break_glass";
export type Id10 = string;
/**
 * Monotonic within an investigation. Replay depends on order, so it is carried rather than inferred from arrival.
 */
export type Sequence = number;
/**
 * Agent codename the grant applies to, e.g. 'argus'.
 */
export type Agent5 = string;
/**
 * Set when mode is ALLOW_UNTIL.
 */
export type ExpiresAt = string | null;
export type GrantedAt = string;
/**
 * Who approved it.
 */
export type GrantedBy = string;
export type Id11 = string;
/**
 * Set when mode is ALLOW_FOR_INVESTIGATION.
 */
export type InvestigationId15 = string | null;
/**
 * How a grant answers a request.
 *
 * ALLOW_UNTIL is refused for production targets and for any write action
 * unless an explicit override is set - see core.cerberus.policy.defaults.
 */
export type PermissionMode = "deny" | "ask_each_time" | "allow_for_investigation" | "allow_until";
/**
 * Explicit override allowing ALLOW_UNTIL on a production or write grant.
 */
export type OverrideAskDefault = boolean;
/**
 * Set when revoked.
 */
export type RevokedAt = string | null;
/**
 * Cerberus credential audit for this run. Safe to expose: every credential here is a CredentialRef, never a value.
 */
export type Audit = AuditEntry[];
export type CompletedAt = string | null;
export type CreatedAt = string;
export type Findings = Finding[];
/**
 * Working hypotheses, before the Verdict ranks them.
 */
export type Hypotheses1 = RootCauseHypothesis[];
export type Id12 = string;
/**
 * Agent codename.
 */
export type Agent6 = string;
/**
 * Agent codenames whose findings this step needs.
 */
export type DependsOn = string[];
export type FinishedAt = string | null;
/**
 * Why this agent is being asked.
 */
export type Reason5 = string;
export type StartedAt = string | null;
/**
 * What Zeus decided to ask.
 */
export type Plan = PlanStep[];
/**
 * A behaviour a model either demonstrably has or does not.
 *
 * Membership is established by probing, never by a hardcoded table - see
 * core.llm.probe.
 */
export type Capability = "tool_use" | "json_mode" | "vision" | "streaming";
/**
 * Probed, not declared.
 */
export type Capabilities1 = Capability[];
export type ContextWindow = number;
export type InputCostPer1K = number | null;
/**
 * Null means never probed; treat capabilities as unknown.
 */
export type LastProbedAt = string | null;
export type MedianLatencyMs = number | null;
export type ModelId = string;
export type OutputCostPer1K = number | null;
export type ProviderId = string;
export type EstimatedCost = number | null;
export type FallbackUsed = boolean;
export type Id13 = string;
/**
 * Which rung of the resolution cascade produced the answer.
 */
export type ResolutionStep = "task_override" | "agent_binding" | "tier_default" | "global_default";
/**
 * Human-readable reason per rejected candidate, in evaluation order.
 */
export type Rejected = string[];
/**
 * Agent codename that consulted Delphi, e.g. 'hermes'.
 */
export type RequestedBy = string;
/**
 * Capabilities the model must demonstrably have.
 */
export type Capabilities2 = Capability[];
/**
 * Ceiling for one call. Enforced via core.guardrails.budget.
 */
export type MaxCostPerCall = number | null;
/**
 * Minimum context window in tokens.
 */
export type MinContext = number;
/**
 * Cost/capability band an agent asks for, rather than a specific model.
 */
export type Tier = "cheap" | "balanced" | "frontier";
export type ResolvedAt = string;
/**
 * Every Delphi model resolution made during this run, in order.
 */
export type Resolutions = ResolutionRecord[];
/**
 * Simulator scenario that produced this run, when triggered by one. Present so a run can be scored against known ground truth.
 */
export type Scenario = string | null;
export type StartedAt1 = string | null;
/**
 * Lifecycle of an Investigation.
 */
export type InvestigationState =
  "pending" | "planning" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";
/**
 * What set an Investigation off.
 */
export type TriggerKind = "alert" | "webhook" | "schedule" | "human_question" | "simulation";
export type ReceivedAt = string;
/**
 * Who sent it, e.g. 'alertmanager'.
 */
export type Source = string;
/**
 * One line, as the source described it.
 */
export type Title1 = string;
/**
 * The only connector that may redeem this lease.
 */
export type Connector2 = string;
export type ExpiresAt1 = string;
export type Id14 = string;
export type InvestigationId16 = string;
export type IssuedAt = string;
/**
 * Auto-renews while the underlying grant is valid and the run is live.
 */
export type Renewable = boolean;
export type RenewedCount = number;
export type RequestId = string;
/**
 * How credentials are presented to a provider.
 */
export type AuthMode = "none" | "bearer" | "header_key" | "query_param";
/**
 * Root URL of the provider's API.
 */
export type BaseUrl = string;
/**
 * Wire format a provider speaks.
 *
 * Named by wire format rather than by vendor: a dialect outlives the vendor
 * that popularised it, and several vendors speak each one.
 *
 * - CHAT_COMPLETIONS: OpenRouter, Groq, Together, DeepSeek, Mistral, vLLM,
 *   LM Studio, Ollama, OpenAI and most self-hosted stacks.
 * - MESSAGES: Anthropic and API-compatible gateways.
 * - GENERATE_CONTENT: Google Gemini.
 * - RAW: bespoke HTTP APIs, mapped by configuration.
 */
export type Dialect = "chat_completions" | "messages" | "generate_content" | "raw";
export type DisplayName = string;
export type Enabled = boolean;
/**
 * Stable identifier, e.g. 'local-ollama'.
 */
export type Id15 = string;
/**
 * Model ids entered by hand when enumeration is absent.
 */
export type ManualModels = string[];
/**
 * Path used to enumerate models, when the provider offers one.
 */
export type ModelsEndpoint = string | null;
/**
 * Cerberus credential reference. Never the credential itself.
 */
export type SecretRef = string | null;
export type ActionName = string;
export type InvestigationId17 = string | null;
export type SourceComponentId = string;
export type SurfaceId = string;

/**
 * Generated from core/contracts/ by codegen/export_schemas.py. Do not edit by hand.
 */
export interface PantheonContracts {
  a2_u_i_client_capabilities?: A2UIClientCapabilities;
  a2_u_i_surface?: A2UISurface;
  access_request?: AccessRequest;
  action?: Action;
  agent_manifest?: AgentManifest;
  audit_entry?: AuditEntry;
  credential_ref?: CredentialRef;
  event_envelope?: EventEnvelope;
  evidence?: Evidence1;
  finding?: Finding;
  grant?: Grant;
  investigation?: Investigation;
  lease?: Lease;
  model_descriptor?: ModelDescriptor;
  model_requirements?: ModelRequirements;
  provider_config?: ProviderConfig;
  resolution_record?: ResolutionRecord;
  root_cause_hypothesis?: RootCauseHypothesis;
  u_i_action_response?: UIActionResponse;
  verdict?: Verdict;
}
/**
 * What the client can render, declared once at run start.
 *
 * A2UI carries this in A2A message metadata (`a2uiClientCapabilities`). AG-UI
 * defines no analog, so this is **Pantheon convention, not specification**: the
 * dashboard sends it in the AG-UI run input, and the agent is told what it may
 * emit before it emits anything.
 *
 * `components` is generated from A2UIComponentType, so what we advertise is
 * exactly what the renderer accepts - there is no second list to keep in step.
 */
export interface A2UIClientCapabilities {
  a2ui_version?: A2UiVersion;
  catalog_id?: CatalogId;
  components?: Components;
}
/**
 * A renderable surface, assembled by Pantheon rather than by an agent.
 *
 * Identity is set here, by the orchestrator, and never by the agent - A2UI
 * calls this out explicitly as an anti-impersonation measure.
 */
export interface A2UISurface {
  a2ui_version?: A2UiVersion1;
  agent_display_name?: AgentDisplayName;
  catalog_id?: CatalogId1;
  components?: Components1;
  data_model?: DataModel;
  icon_url?: IconUrl;
  id: Id1;
  investigation_id?: InvestigationId1;
  kind: A2UISurfaceKind;
  root: Root;
}
/**
 * One component in a surface. Authored by an agent, rendered by the host.
 *
 * Note what is absent: no styling, no HTML, no script, and no identity fields.
 * ``icon_url`` and ``agent_display_name`` live on A2UISurface and are set by
 * the orchestrator, so an agent cannot present itself as another agent or as
 * Pantheon itself.
 */
export interface A2UIComponent {
  action?: A2UIAction | null;
  /**
   * For Image. A reference Pantheon resolves; never a URL an agent supplies.
   */
  artifact_ref?: ArtifactRef | null;
  children?: Children;
  component: A2UIComponentType1;
  data_path?: DataPath;
  id: Id;
  label?: Label;
  text?: Text;
}
/**
 * A declared action on a component.
 *
 * A2UI carries either a server event or a local function call, both referenced
 * **by name**. No executable code crosses the boundary in either direction.
 */
export interface A2UIAction {
  context?: Context;
  event_name?: EventName;
  function_call?: FunctionCall;
}
/**
 * Values returned with the action.
 */
export interface Context {
  [k: string]: unknown;
}
/**
 * A reference to an artifact Pantheon produced and stored. Never a URL.
 *
 * Same shape as CredentialRef, for the same reason: the agent names a thing it
 * is allowed to name, and the server resolves it. A URL field would let an
 * agent express an arbitrary destination, and the browser fetching it is a
 * data-exfiltration channel - the agent encodes what it learned into the URL
 * and the browser delivers it.
 *
 * A server-side URL proxy was considered and rejected. It still accepts an
 * agent-authored URL and defends by filtering, which is one bypass away from
 * failing. A reference has nothing to filter.
 *
 * Note what is absent: no URL, no host, no bucket. The bucket is fixed
 * server-side, so the agent cannot name one. Resolution happens only in
 * core.ui.artifact_resolution, which agents cannot import - the same boundary
 * as core.cerberus.redemption.
 */
export interface ArtifactRef {
  alt_text?: AltText;
  investigation_id: InvestigationId;
  key: Key;
  kind?: ArtifactKind;
}
/**
 * Initial values bound by JSON Pointer.
 */
export interface DataModel {
  [k: string]: unknown;
}
/**
 * An agent asking for a capability, with the reason it is asking.
 *
 * `reason` is not decoration. Approving "an agent wants database access" is
 * not a decision; approving a stated hypothesis is.
 */
export interface AccessRequest {
  action: CredentialAction;
  agent: Agent;
  credential_ref: CredentialRef;
  id: Id3;
  investigation_id: InvestigationId2;
  reason: Reason;
  requested_at: RequestedAt;
  requested_ttl_seconds: RequestedTtlSeconds;
}
/**
 * A reference to a stored credential. Never the credential.
 *
 * Safe to persist, to attach to an Investigation and to render in the
 * dashboard, because it identifies without disclosing.
 */
export interface CredentialRef {
  id: Id2;
  name: Name;
  scope?: CredentialScope;
  type: CredentialType;
}
/**
 * Where a credential applies: a server, a service, an environment.
 */
export interface CredentialScope {
  environment?: Environment;
  server?: Server;
  service?: Service;
}
/**
 * A remediation Pantheon proposes, and may later execute.
 */
export interface Action {
  approval_state?: ApprovalState;
  blast_radius: BlastRadius;
  dry_run?: DryRun;
  execution_state?: ExecutionState;
  id: Id4;
  operation: Operation;
  parameters?: Parameters;
  proposed_at: ProposedAt;
  proposed_by: ProposedBy;
  reason: Reason1;
  receipts?: Receipts;
  rollback?: Rollback;
  target: ResourceRef;
}
/**
 * Operation arguments, e.g. {'replicas': 4}.
 */
export interface Parameters {
  [k: string]: unknown;
}
/**
 * What happened when an Action ran. Written once, never amended.
 */
export interface ActionReceipt {
  at: At;
  connector: Connector;
  detail?: Detail;
  lease_id?: LeaseId;
  state: ExecutionState1;
}
/**
 * What a piece of Evidence is about.
 *
 * Deliberately not Kubernetes-shaped: a pipeline and a database are subjects
 * too, and forcing them into `namespace/kind/name` would be a lie that costs
 * an adapter at every call site.
 */
export interface ResourceRef {
  cluster?: Cluster;
  kind: Kind;
  name: Name1;
  namespace?: Namespace;
}
/**
 * Everything the registry needs to know about an agent without importing it.
 */
export interface AgentManifest {
  budget: AgentBudget;
  capabilities?: Capabilities;
  codename: Codename;
  description: Description1;
  domain: Domain;
  tools?: Tools;
}
/**
 * Ceilings the dispatcher enforces for a single agent invocation.
 */
export interface AgentBudget {
  max_seconds: MaxSeconds;
  max_tokens: MaxTokens;
  max_tool_calls: MaxToolCalls;
}
/**
 * One thing an agent claims it can do.
 */
export interface AgentCapability {
  description: Description;
  name: Name2;
}
/**
 * One immutable line in the credential audit log.
 *
 * Attached to the Investigation, which agents can see - safe because every
 * reference here is a CredentialRef and never a value.
 */
export interface AuditEntry {
  action?: CredentialAction1;
  actor: Actor;
  at: At1;
  credential_ref?: CredentialRef | null;
  detail?: Detail1;
  event: AuditEvent;
  id: Id5;
  investigation_id?: InvestigationId3;
  lease_id?: LeaseId1;
}
/**
 * Transport wrapper carrying one event plus its correlation metadata.
 */
export interface EventEnvelope {
  emitted_at: EmittedAt;
  event: Event;
  id: Id10;
  sequence?: Sequence;
}
/**
 * An Investigation moved out of PENDING.
 */
export interface InvestigationStartedEvent {
  investigation_id: InvestigationId4;
  type?: Type;
}
/**
 * A run reached a terminal state, successfully or not.
 */
export interface InvestigationCompletedEvent {
  investigation_id: InvestigationId5;
  partial?: Partial;
  state: State;
  type?: Type1;
}
/**
 * Zeus dispatched an agent.
 */
export interface StepStartedEvent {
  agent: Agent1;
  investigation_id: InvestigationId6;
  type?: Type2;
}
/**
 * An agent returned, with or without findings.
 */
export interface StepFinishedEvent {
  agent: Agent2;
  finding_count?: FindingCount;
  investigation_id: InvestigationId7;
  type?: Type3;
}
/**
 * An agent returned a Finding.
 */
export interface FindingProducedEvent {
  finding: Finding;
  investigation_id: InvestigationId8;
  type?: Type4;
}
/**
 * One agent's supported claim about what it observed.
 */
export interface Finding {
  agent: Agent3;
  confidence: Confidence;
  detected_at: DetectedAt;
  evidence?: Evidence;
  id: Id7;
  kind?: FindingKind;
  rationale?: Rationale;
  severity: Severity;
  /**
   * What the claim is about.
   */
  subject?: ResourceRef | null;
  tags?: Tags;
  title: Title;
  window_end?: WindowEnd;
  window_start?: WindowStart;
}
/**
 * A single observation, attributable to one connector at one moment.
 */
export interface Evidence1 {
  id: Id6;
  observed_at: ObservedAt;
  payload: Payload;
  source: EvidenceSource;
  /**
   * What this is about, when it is about one thing.
   */
  subject?: ResourceRef | null;
  summary: Summary;
}
/**
 * A slice of a time series, with the baseline it is being judged against.
 *
 * `deviation_sigma` is carried rather than recomputed downstream so that the
 * dashboard, the verdict and the audit trail all agree on how unusual this
 * was - recomputing invites three different answers.
 */
export interface MetricWindowPayload {
  baseline_mean?: BaselineMean;
  baseline_stddev?: BaselineStddev;
  deviation_sigma?: DeviationSigma;
  kind?: Kind1;
  metric: Metric;
  samples?: Samples;
  unit?: Unit;
  window_seconds?: WindowSeconds;
}
/**
 * One point on a series.
 */
export interface MetricSample {
  at: At2;
  value: Value;
}
/**
 * A group of log lines sharing a template, plus how surprising it is.
 */
export interface LogClusterPayload {
  first_seen?: FirstSeen;
  kind?: Kind2;
  last_seen?: LastSeen;
  novelty?: Novelty;
  occurrences?: Occurrences;
  sample_lines?: SampleLines;
  template: Template;
}
/**
 * A change to a manifest or IaC definition, and what it touches.
 */
export interface ManifestDiffPayload {
  changed_fields?: ChangedFields;
  diff: Diff;
  kind?: Kind3;
  revision_after?: RevisionAfter;
  revision_before?: RevisionBefore;
  target: ResourceRef;
}
/**
 * A Kubernetes event, which is often the shortest path to the answer.
 */
export interface K8SEventPayload {
  count?: Count;
  event_type?: EventType;
  first_seen?: FirstSeen1;
  kind?: Kind4;
  last_seen?: LastSeen1;
  message: Message;
  reason: Reason2;
  target: ResourceRef;
}
/**
 * One CI pipeline run and the jobs that failed in it.
 */
export interface PipelineRunPayload {
  commit_sha?: CommitSha;
  duration_seconds?: DurationSeconds;
  failed_jobs?: FailedJobs;
  kind?: Kind5;
  pipeline_id: PipelineId;
  project: Project;
  ref: Ref;
  status: Status;
}
/**
 * Where a piece of Evidence came from, so a human can go and look.
 */
export interface EvidenceSource {
  collected_at?: CollectedAt;
  connector: Connector1;
  query?: Query;
}
/**
 * A candidate explanation entered the running.
 */
export interface HypothesisProposedEvent {
  hypothesis: RootCauseHypothesis;
  investigation_id: InvestigationId9;
  type?: Type5;
}
/**
 * One candidate explanation, and how well it survived contact with evidence.
 */
export interface RootCauseHypothesis {
  category: RootCauseCategory;
  confidence: Confidence1;
  contradicting_finding_ids?: ContradictingFindingIds;
  id: Id8;
  proposed_by: ProposedBy1;
  reasoning?: Reasoning;
  statement: Statement;
  status?: HypothesisStatus;
  subject?: Subject;
  supporting_finding_ids?: SupportingFindingIds;
}
/**
 * The aggregator reached a conclusion.
 */
export interface VerdictReadyEvent {
  investigation_id: InvestigationId10;
  type?: Type6;
  verdict: Verdict;
}
/**
 * The orchestrator's ranked conclusion for one Investigation.
 */
export interface Verdict {
  confidence: Confidence2;
  contributing_findings?: ContributingFindings;
  decided_at: DecidedAt;
  hypotheses?: Hypotheses;
  id: Id9;
  investigation_id: InvestigationId11;
  partial?: Partial1;
  recommended_actions?: RecommendedActions;
  summary: Summary1;
}
/**
 * An Action needs a human before it can execute.
 */
export interface ApprovalRequestedEvent {
  action: Action;
  investigation_id: InvestigationId12;
  type?: Type7;
}
/**
 * An agent asked Cerberus for a capability it has no standing grant for.
 */
export interface AccessRequestedEvent {
  investigation_id: InvestigationId13;
  request: AccessRequest;
  type?: Type8;
}
/**
 * A lease could not be renewed, so the work behind it stopped.
 *
 * ADR 0005: this must surface as a Finding and never be swallowed. `reason`
 * distinguishes the two cases, because they call for opposite responses -
 * an expired grant warrants offering re-approval, a revoked one must not,
 * since re-prompting would undo a deliberate revocation mid-incident.
 */
export interface LeaseExpiredEvent {
  agent: Agent4;
  investigation_id: InvestigationId14;
  lease_id: LeaseId2;
  reason?: Reason3;
  type?: Type9;
}
/**
 * Every grant revoked and every live lease invalidated, immediately.
 *
 * The one domain concept that becomes an AG-UI `Custom` event rather than a
 * state patch: it affects every run at once, so an open dashboard must react
 * on arrival rather than render a new audit row (ADR 0006).
 */
export interface BreakGlassEvent {
  audit_entry?: AuditEntry | null;
  invoked_by: InvokedBy;
  leases_revoked?: LeasesRevoked;
  reason: Reason4;
  type?: Type10;
}
/**
 * Standing permission for one agent to reach one credential one way.
 */
export interface Grant {
  action: CredentialAction;
  agent: Agent5;
  credential_ref: CredentialRef;
  expires_at?: ExpiresAt;
  granted_at: GrantedAt;
  granted_by: GrantedBy;
  id: Id11;
  investigation_id?: InvestigationId15;
  mode: PermissionMode;
  override_ask_default?: OverrideAskDefault;
  revoked_at?: RevokedAt;
}
/**
 * One end-to-end run, from trigger to Verdict.
 */
export interface Investigation {
  audit?: Audit;
  completed_at?: CompletedAt;
  created_at: CreatedAt;
  findings?: Findings;
  hypotheses?: Hypotheses1;
  id: Id12;
  plan?: Plan;
  resolutions?: Resolutions;
  scenario?: Scenario;
  started_at?: StartedAt1;
  state: InvestigationState;
  trigger: Trigger;
  /**
   * Absent until the run reaches a conclusion.
   */
  verdict?: Verdict | null;
}
/**
 * One agent consultation Zeus intends to make.
 */
export interface PlanStep {
  agent: Agent6;
  depends_on?: DependsOn;
  finished_at?: FinishedAt;
  reason: Reason5;
  started_at?: StartedAt;
}
/**
 * Why Delphi chose the model it chose, for one call.
 *
 * Attached to the Investigation so a run is reproducible and can explain its
 * own cost without being re-run.
 */
export interface ResolutionRecord {
  chosen: ModelDescriptor;
  estimated_cost?: EstimatedCost;
  fallback_used?: FallbackUsed;
  id: Id13;
  matched_step: ResolutionStep;
  rejected?: Rejected;
  requested_by: RequestedBy;
  requirements: ModelRequirements;
  resolved_at: ResolvedAt;
}
/**
 * One model as observed, not as advertised.
 *
 * Every field below the identity pair is measured by core.llm.probe against
 * this deployment, because a model's behaviour behind a particular gateway is
 * not always what its vendor documents.
 */
export interface ModelDescriptor {
  capabilities?: Capabilities1;
  context_window?: ContextWindow;
  input_cost_per_1k?: InputCostPer1K;
  last_probed_at?: LastProbedAt;
  median_latency_ms?: MedianLatencyMs;
  model_id: ModelId;
  output_cost_per_1k?: OutputCostPer1K;
  provider_id: ProviderId;
}
/**
 * What an agent needs from a model. The only thing an agent may declare.
 */
export interface ModelRequirements {
  capabilities?: Capabilities2;
  max_cost_per_call?: MaxCostPerCall;
  min_context?: MinContext;
  tier?: Tier;
}
/**
 * The inbound event that started everything.
 */
export interface Trigger {
  kind: TriggerKind;
  payload?: Payload1;
  received_at: ReceivedAt;
  source: Source;
  title?: Title1;
}
/**
 * Verbatim, unparsed.
 */
export interface Payload1 {
  [k: string]: unknown;
}
/**
 * Permission to use a credential, bound to one connector and one run.
 *
 * A lease is not a credential. It is redeemable only by the named connector,
 * only for the named investigation, and only until it expires - so a leaked
 * lease is worthless anywhere else.
 */
export interface Lease {
  action: CredentialAction;
  connector: Connector2;
  credential_ref: CredentialRef;
  expires_at: ExpiresAt1;
  id: Id14;
  investigation_id: InvestigationId16;
  issued_at: IssuedAt;
  renewable?: Renewable;
  renewed_count?: RenewedCount;
  request_id: RequestId;
}
/**
 * A configured provider. Added from settings, never from code.
 */
export interface ProviderConfig {
  auth_mode?: AuthMode;
  base_url: BaseUrl;
  dialect: Dialect;
  display_name: DisplayName;
  enabled?: Enabled;
  id: Id15;
  manual_models?: ManualModels;
  models_endpoint?: ModelsEndpoint;
  secret_ref?: SecretRef;
}
/**
 * A user's response to an action, travelling back over AG-UI.
 *
 * Mirrors A2UI's client action message. Carries no decision authority of its
 * own: an approval reaching the Approval Gate, or an access decision reaching
 * Cerberus, is re-validated there against the request it claims to answer.
 */
export interface UIActionResponse {
  action_name: ActionName;
  context?: Context1;
  investigation_id?: InvestigationId17;
  source_component_id: SourceComponentId;
  surface_id: SurfaceId;
}
export interface Context1 {
  [k: string]: unknown;
}
