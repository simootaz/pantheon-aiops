/**
 * The dashboard's REST reads. One place, so the token is attached once.
 *
 * The AG-UI stream carries a run as it happens; these are the reads that answer
 * "what ran recently" and "what is waiting for me", which no stream can - a
 * stream is about one investigation and starts when you open it.
 *
 * THE TOKEN TRAVELS IN A HEADER
 * -----------------------------
 * Same rule as `stream.ts`, `connectors/github` and `connectors/gitlab`: a
 * credential in a query string lands in the reverse proxy's access log and in
 * the browser's history. There is no code path here that puts one in a URL.
 *
 * A REFUSAL IS NOT AN EMPTY LIST
 * ------------------------------
 * Every function throws `ApiError` carrying the status. A caller that turned a
 * 401 into `[]` would render "no investigations" to somebody whose token
 * expired, and they would go looking for a run that is sitting right there.
 *
 * Phase: 4 - Delivery Flow
 */
import type { Investigation } from "@/types/generated/contracts";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** A request the API refused, with the status so a view can branch. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Whether this failure means "sign in again" rather than "try later". */
export function isAuthFailure(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

async function read<T>(path: string, token: string | null): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;

  const response = await fetch(`${API_URL}${path}`, { headers, cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(response.status, `${path} answered ${response.status}`);
  }
  return (await response.json()) as T;
}

async function send<T>(path: string, token: string | null, body: unknown): Promise<T> {
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
  };
  if (token) headers.authorization = `Bearer ${token}`;

  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${path} answered ${response.status}`);
  }
  return (await response.json()) as T;
}

/**
 * Recent investigations, newest first.
 *
 * The server narrows these to the caller's tenant. This does not pass a tenant
 * and must not gain the ability to: a `?tenant=` would be a claim rather than a
 * fact, and the endpoint would become an invitation to read somebody else's
 * runs by typing their name.
 */
export function recentInvestigations(token: string | null, limit = 20): Promise<Investigation[]> {
  return read<Investigation[]>(`/investigations?limit=${limit}`, token);
}

/** One investigation, whole. 404 covers "no such run" and "not yours" alike. */
export function investigation(id: string, token: string | null): Promise<Investigation> {
  return read<Investigation>(`/investigations/${id}`, token);
}

/**
 * One request waiting for a person.
 *
 * Declared here rather than imported from the generated contracts because it is
 * not one: `ApprovalRequest.as_dict` in `core/guardrails/approval_gate.py` is an
 * API shape, and the generator covers `core/contracts` only. Its docstring says
 * no credential ever passes through it, and nothing here asks for one.
 */
export interface PendingApproval {
  id: string;
  action_id: string;
  proposed_by: string;
  opened_at: string;
  expires_at: string;
  answered_by: string | null;
  reason: string | null;
  rule: string;
}

/** Requests waiting for a person. Oldest first; expired ones are not listed. */
export function pendingApprovals(token: string | null): Promise<PendingApproval[]> {
  return read<PendingApproval[]>("/approvals", token);
}

/** Answer one. `approve` false is a rejection, which is also an answer. */
export function respondToApproval(
  requestId: string,
  approve: boolean,
  answeredBy: string,
  token: string | null,
): Promise<PendingApproval> {
  return send<PendingApproval>(`/approvals/${requestId}`, token, {
    approve,
    answered_by: answeredBy,
  });
}

/**
 * A row on the agent roster.
 *
 * `implemented` is the field that matters: the registry lists every agent the
 * platform names, and most of them are manifests with no code behind them yet.
 * A roster that hid that would be a list of promises.
 */
export interface AgentSummary {
  codename: string;
  domain: string;
  description: string;
  capabilities: string[];
  tools: string[];
  implemented: boolean;
}

/** Every agent on the roster, implemented or not. */
export function agents(token: string | null): Promise<AgentSummary[]> {
  return read<AgentSummary[]>("/agents", token);
}
