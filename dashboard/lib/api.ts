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
import type { Action, Investigation } from "@/types/generated/contracts";

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
  /** The policy rule that sent this to a person. */
  rule: string;
  /** Why that rule fired, in the rule's own words. */
  because: string;
  /**
   * The Action as proposed - what the approver is asked to read.
   *
   * Nullable because a persisted row written before the gate carried one
   * cannot grow it retrospectively. A view must degrade to "id and rule" for
   * such a row rather than offer a button, because a button there would be
   * "approve action 7f3a?" - the prompt `core/ui/approval.py` refuses to emit.
   */
  action: Action | null;
}

/** Requests waiting for a person. Oldest first; expired ones are not listed. */
export function pendingApprovals(token: string | null): Promise<PendingApproval[]> {
  return read<PendingApproval[]>("/approvals", token);
}

/**
 * Answer one. `approve` false is a rejection, which is also an answer.
 *
 * WHO IS ANSWERING IS NOT IN THE BODY
 * -----------------------------------
 * It comes from the bearer token. `api/routers/approvals.py` removed the
 * `approver` field for the reason its docstring gives: the gate refuses a
 * proposer approving their own request, and checking that against a name the
 * caller just chose makes the rule hold for as long as they cooperate.
 *
 * THE ACTION GOES BACK IN
 * -----------------------
 * The gate re-validates the answer against the content the approver read. From
 * here that check compares a served copy against itself and proves nothing -
 * `may_execute` at execution time is what protects the run, against the Action
 * the executor holds. Sending it anyway because the endpoint's contract is
 * written for the caller that holds its own copy, and quietly omitting it
 * would be a 422.
 */
export function respondToApproval(
  requestId: string,
  approve: boolean,
  action: Action,
  reason: string,
  token: string | null,
): Promise<PendingApproval> {
  return send<PendingApproval>(`/approvals/${requestId}`, token, { approve, reason, action });
}

/**
 * A row on the agent roster.
 *
 * TWO FIELDS, BECAUSE THEY ARE TWO FACTS
 * --------------------------------------
 * `implemented` says code exists. `dispatchable` says a trigger can produce a
 * plan that names it, and is narrower. Themis is the case that forces the
 * split: written, tooled and tested, and unreachable until something schedules
 * anything - on one field it read exactly as Clio does, and Clio is a manifest
 * with nothing behind it.
 *
 * A roster with neither would be a list of promises.
 */
export interface AgentSummary {
  codename: string;
  domain: string;
  description: string;
  capabilities: string[];
  tools: string[];
  implemented: boolean;
  dispatchable: boolean;
}

/** Every agent on the roster, implemented or not. */
export function agents(token: string | null): Promise<AgentSummary[]> {
  return read<AgentSummary[]>("/agents", token);
}
