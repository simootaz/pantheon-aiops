/* eslint-disable */
/**
 * Generated from core/contracts/ by codegen/gen_ts.sh. DO NOT EDIT BY HAND.
 *
 * Source of truth: core/contracts/ (Pydantic v2), via
 * core/contracts/export/pantheon.schema.json. Regenerate with: make codegen
 */

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
export type Id = string;
/**
 * What it does, e.g. 'rollout_restart'.
 */
export type Operation = string;
/**
 * Why this Action was proposed.
 */
export type Reason = string | null;
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
export type Name = string;
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
export type EmittedAt = string;
export type Event = InvestigationStartedEvent | FindingProducedEvent | VerdictReadyEvent | ApprovalRequestedEvent;
export type InvestigationId = string;
export type Type = "investigation_started";
/**
 * Codename of the agent that produced it, e.g. 'argus'.
 */
export type Agent = string;
/**
 * Agent's own confidence, 0 to 1.
 */
export type Confidence = number;
export type Id1 = string;
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
export type Id2 = string;
/**
 * Why the Evidence supports the claim.
 */
export type Rationale = string | null;
/**
 * How much a Finding should worry the on-call engineer.
 */
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type Title = string;
export type InvestigationId1 = string;
export type Type1 = "finding_produced";
export type InvestigationId2 = string;
export type Type2 = "verdict_ready";
export type Confidence1 = number;
export type ContributingFindings = Finding[];
export type Id3 = string;
export type InvestigationId3 = string;
export type RecommendedActions = Action[];
/**
 * Null when the evidence does not support a conclusion.
 */
export type RootCause = string | null;
export type Summary1 = string;
export type InvestigationId4 = string;
export type Type3 = "approval_requested";
export type Id4 = string;
export type CompletedAt = string | null;
export type CreatedAt = string;
export type Findings = Finding[];
export type Id5 = string;
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
export type Id6 = string;
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
export type Id7 = string;
/**
 * Model ids entered by hand when enumeration is absent.
 */
export type ManualModels = string[];
/**
 * Path used to enumerate models, when the provider offers one.
 */
export type ModelsEndpoint = string | null;
/**
 * Name of the credential in the keyring. Never the credential itself.
 */
export type SecretRef = string | null;

/**
 * Generated from core/contracts/ by codegen/export_schemas.py. Do not edit by hand.
 */
export interface PantheonContracts {
  action?: Action;
  agent_manifest?: AgentManifest;
  event_envelope?: EventEnvelope;
  evidence?: Evidence1;
  finding?: Finding;
  investigation?: Investigation;
  model_descriptor?: ModelDescriptor;
  model_requirements?: ModelRequirements;
  provider_config?: ProviderConfig;
  resolution_record?: ResolutionRecord;
  verdict?: Verdict;
}
/**
 * A remediation Pantheon proposes, and may later execute.
 */
export interface Action {
  approval_state?: ApprovalState;
  blast_radius: BlastRadius;
  dry_run?: DryRun;
  id: Id;
  operation: Operation;
  reason?: Reason;
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
  name: Name;
}
/**
 * Transport wrapper carrying one event plus its correlation metadata.
 */
export interface EventEnvelope {
  emitted_at: EmittedAt;
  event: Event;
  id: Id4;
}
/**
 * An Investigation moved out of PENDING.
 */
export interface InvestigationStartedEvent {
  investigation_id: InvestigationId;
  type?: Type;
}
/**
 * An agent returned a Finding.
 */
export interface FindingProducedEvent {
  finding: Finding;
  investigation_id: InvestigationId1;
  type?: Type1;
}
/**
 * One agent's supported claim about what it observed.
 */
export interface Finding {
  agent: Agent;
  confidence: Confidence;
  evidence?: Evidence;
  id: Id2;
  rationale?: Rationale;
  severity: Severity;
  title: Title;
}
/**
 * A single observation, attributable to one connector at one moment.
 */
export interface Evidence1 {
  id: Id1;
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
  investigation_id: InvestigationId2;
  type?: Type2;
  verdict: Verdict;
}
/**
 * The orchestrator's ranked conclusion for one Investigation.
 */
export interface Verdict {
  confidence: Confidence1;
  contributing_findings?: ContributingFindings;
  id: Id3;
  investigation_id: InvestigationId3;
  recommended_actions?: RecommendedActions;
  root_cause?: RootCause;
  summary: Summary1;
}
/**
 * An Action needs a human before it can execute.
 */
export interface ApprovalRequestedEvent {
  action: Action;
  investigation_id: InvestigationId4;
  type?: Type3;
}
/**
 * One end-to-end run, from trigger to Verdict.
 */
export interface Investigation {
  completed_at?: CompletedAt;
  created_at: CreatedAt;
  findings?: Findings;
  id: Id5;
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
  id: Id6;
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
 * A configured provider. Added from settings, never from code.
 */
export interface ProviderConfig {
  auth_mode?: AuthMode;
  base_url: BaseUrl;
  dialect: Dialect;
  display_name: DisplayName;
  enabled?: Enabled;
  id: Id7;
  manual_models?: ManualModels;
  models_endpoint?: ModelsEndpoint;
  secret_ref?: SecretRef;
}
