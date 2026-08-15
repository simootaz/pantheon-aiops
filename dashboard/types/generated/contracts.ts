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
export type ApprovalState = "not_required" | "pending" | "approved" | "rejected";
/**
 * How much can break if this Action is wrong.
 */
export type BlastRadius = "none" | "single_workload" | "namespace" | "cluster";
/**
 * Dry run until explicitly cleared.
 */
export type DryRun = boolean;
export type Id4 = string;
/**
 * What it does, e.g. 'rollout_restart'.
 */
export type Operation = string;
/**
 * Why this Action was proposed.
 */
export type Reason1 = string | null;
/**
 * What it acts on, e.g. 'deployment/checkout'.
 */
export type Target = string;
export type MaxSeconds = number;
export type MaxTokens = number;
export type MaxToolCalls = number;
export type Description = string;
/**
 * Stable identifier, e.g. 'detect_metric_anomaly'.
 */
export type Name1 = string;
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
export type At = string;
/**
 * Human-readable context. Never a credential.
 */
export type Detail = string;
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
export type LeaseId = string | null;
export type EmittedAt = string;
export type Event = InvestigationStartedEvent | FindingProducedEvent | VerdictReadyEvent | ApprovalRequestedEvent;
export type InvestigationId4 = string;
export type Type = "investigation_started";
/**
 * Codename of the agent that produced it, e.g. 'argus'.
 */
export type Agent1 = string;
/**
 * Agent's own confidence, 0 to 1.
 */
export type Confidence = number;
export type Id6 = string;
/**
 * What sort of observation this Evidence carries.
 */
export type EvidenceKind = "metric_window" | "log_cluster" | "manifest_diff" | "k8s_event" | "pipeline_run";
export type ObservedAt = string;
/**
 * Connector that produced it, e.g. 'prometheus'.
 */
export type Connector = string;
/**
 * Query that produced it, if any.
 */
export type Query = string | null;
/**
 * One-line human-readable description.
 */
export type Summary = string;
/**
 * Evidence supporting the claim. A Finding with none is inadmissible.
 */
export type Evidence = Evidence1[];
export type Id7 = string;
/**
 * Why the Evidence supports the claim.
 */
export type Rationale = string | null;
/**
 * How much a Finding should worry the on-call engineer.
 */
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type Title = string;
export type InvestigationId5 = string;
export type Type1 = "finding_produced";
export type InvestigationId6 = string;
export type Type2 = "verdict_ready";
export type Confidence1 = number;
export type ContributingFindings = Finding[];
export type Id8 = string;
export type InvestigationId7 = string;
export type RecommendedActions = Action[];
/**
 * Null when the evidence does not support a conclusion.
 */
export type RootCause = string | null;
export type Summary1 = string;
export type InvestigationId8 = string;
export type Type3 = "approval_requested";
export type Id9 = string;
/**
 * Agent codename the grant applies to, e.g. 'argus'.
 */
export type Agent2 = string;
/**
 * Set when mode is ALLOW_UNTIL.
 */
export type ExpiresAt = string | null;
export type GrantedAt = string;
/**
 * Who approved it.
 */
export type GrantedBy = string;
export type Id10 = string;
/**
 * Set when mode is ALLOW_FOR_INVESTIGATION.
 */
export type InvestigationId9 = string | null;
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
export type Id11 = string;
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
export type Id12 = string;
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
 * Lifecycle of an Investigation.
 */
export type InvestigationState =
  "pending" | "planning" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";
/**
 * What set an Investigation off.
 */
export type TriggerKind = "alert" | "webhook" | "schedule" | "human_question";
export type ReceivedAt = string;
/**
 * Who sent it, e.g. 'alertmanager'.
 */
export type Source = string;
/**
 * The only connector that may redeem this lease.
 */
export type Connector1 = string;
export type ExpiresAt1 = string;
export type Id13 = string;
export type InvestigationId10 = string;
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
export type Id14 = string;
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
export type InvestigationId11 = string | null;
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
  id: Id4;
  operation: Operation;
  reason?: Reason1;
  target: Target;
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
  name: Name1;
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
  at: At;
  credential_ref?: CredentialRef | null;
  detail?: Detail;
  event: AuditEvent;
  id: Id5;
  investigation_id?: InvestigationId3;
  lease_id?: LeaseId;
}
/**
 * Transport wrapper carrying one event plus its correlation metadata.
 */
export interface EventEnvelope {
  emitted_at: EmittedAt;
  event: Event;
  id: Id9;
}
/**
 * An Investigation moved out of PENDING.
 */
export interface InvestigationStartedEvent {
  investigation_id: InvestigationId4;
  type?: Type;
}
/**
 * An agent returned a Finding.
 */
export interface FindingProducedEvent {
  finding: Finding;
  investigation_id: InvestigationId5;
  type?: Type1;
}
/**
 * One agent's supported claim about what it observed.
 */
export interface Finding {
  agent: Agent1;
  confidence: Confidence;
  evidence?: Evidence;
  id: Id7;
  rationale?: Rationale;
  severity: Severity;
  title: Title;
}
/**
 * A single observation, attributable to one connector at one moment.
 */
export interface Evidence1 {
  id: Id6;
  kind: EvidenceKind;
  observed_at: ObservedAt;
  payload?: Payload;
  source: EvidenceSource;
  summary: Summary;
}
/**
 * Kind-specific body. Phase 1 replaces this with per-kind models.
 */
export interface Payload {
  [k: string]: unknown;
}
/**
 * Where a piece of Evidence came from, so a human can go look themselves.
 */
export interface EvidenceSource {
  connector: Connector;
  query?: Query;
}
/**
 * The aggregator reached a conclusion.
 */
export interface VerdictReadyEvent {
  investigation_id: InvestigationId6;
  type?: Type2;
  verdict: Verdict;
}
/**
 * The orchestrator's ranked conclusion for one Investigation.
 */
export interface Verdict {
  confidence: Confidence1;
  contributing_findings?: ContributingFindings;
  id: Id8;
  investigation_id: InvestigationId7;
  recommended_actions?: RecommendedActions;
  root_cause?: RootCause;
  summary: Summary1;
}
/**
 * An Action needs a human before it can execute.
 */
export interface ApprovalRequestedEvent {
  action: Action;
  investigation_id: InvestigationId8;
  type?: Type3;
}
/**
 * Standing permission for one agent to reach one credential one way.
 */
export interface Grant {
  action: CredentialAction;
  agent: Agent2;
  credential_ref: CredentialRef;
  expires_at?: ExpiresAt;
  granted_at: GrantedAt;
  granted_by: GrantedBy;
  id: Id10;
  investigation_id?: InvestigationId9;
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
  id: Id11;
  resolutions?: Resolutions;
  state: InvestigationState;
  trigger: Trigger;
  /**
   * Absent until the run reaches a conclusion.
   */
  verdict?: Verdict | null;
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
  id: Id12;
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
}
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
  connector: Connector1;
  credential_ref: CredentialRef;
  expires_at: ExpiresAt1;
  id: Id13;
  investigation_id: InvestigationId10;
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
  id: Id14;
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
  investigation_id?: InvestigationId11;
  source_component_id: SourceComponentId;
  surface_id: SurfaceId;
}
export interface Context1 {
  [k: string]: unknown;
}
