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
export type Capabilities = Capability[];
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
 * Generated from core/contracts/ by codegen/export_schemas.py. Do not edit by hand.
 */
export interface PantheonContracts {
  action?: Action;
  agent_manifest?: AgentManifest;
  event_envelope?: EventEnvelope;
  evidence?: Evidence1;
  finding?: Finding;
  investigation?: Investigation;
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
export interface Capability {
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
  state: InvestigationState;
  trigger: Trigger;
  /**
   * Absent until the run reaches a conclusion.
   */
  verdict?: Verdict | null;
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
