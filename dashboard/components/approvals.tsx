/**
 * The approval card, in the browser.
 *
 * The same content `core/ui/approval.py` puts on the A2UI surface: target,
 * blast radius, rollback, and why the Action was proposed. Not an id.
 * "Approve action 7f3a?" is a prompt people learn to click through, and a gate
 * answered by reflex records a decision nobody made - which is worse than no
 * gate, because the audit trail then says a person weighed it.
 *
 * A REJECTION HAS TO SAY WHY
 * --------------------------
 * The API accepts an empty reason; this does not offer one. `reason` is the
 * first thing read on a rejection, and a proposer told only "no" learns nothing
 * about what to change. An approval needs no such text: the Action itself is
 * the record of what was agreed to.
 *
 * A REQUEST WITH NO ACTION GETS NO BUTTONS
 * ----------------------------------------
 * The gate's `action` is nullable - a persisted row written before the field
 * existed cannot grow one. Such a row is still listed, because hiding it would
 * lose a request that is genuinely waiting, but it is not answerable here: a
 * button beside an id with no content is exactly the prompt this file exists to
 * avoid.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { type JSX, useState } from "react";
import type { PendingApproval } from "@/lib/api";
import type { Action } from "@/types/generated/contracts";

/** How much of the estate one Action can touch, worst first. */
const RADIUS_TONE: Record<string, string> = {
  multi_cluster: "text-red-700 dark:text-red-400",
  cluster: "text-red-700 dark:text-red-400",
  namespace: "text-amber-600 dark:text-amber-400",
  single_workload: "text-slate-600 dark:text-slate-400",
  none: "text-slate-600 dark:text-slate-400",
};

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <div>
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** What the Action does, laid out the way the A2UI card lays it out. */
export function ActionDetail({ action }: { action: Action }): JSX.Element {
  return (
    <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
      <Field label="Target">
        {action.target.kind}/{action.target.name}
        {action.target.namespace ? ` in ${action.target.namespace}` : ""}
      </Field>
      <Field label="Blast radius">
        <span className={RADIUS_TONE[action.blast_radius] ?? ""}>{action.blast_radius}</span>
      </Field>
      <Field label="Rollback">
        {/* Said out loud when there is none. `core/contracts/action.py` refuses
            to build anything wider than one workload without a rollback, so an
            absent one here means the Action is narrow - and an approver should
            read that as a fact rather than as a field that failed to load. */}
        {action.rollback ?? (
          <span className="text-slate-500 dark:text-slate-400">
            none stated - single workload or narrower
          </span>
        )}
      </Field>
      <Field label="Dry run">
        {action.dry_run === false ? "no - this will change the system" : "yes"}
      </Field>
      <div className="sm:col-span-2">
        <dt className="text-xs text-slate-500 dark:text-slate-400">Reason</dt>
        <dd>{action.reason}</dd>
      </div>
    </dl>
  );
}

export interface ApprovalCardProps {
  approval: PendingApproval;
  /** Called with the verdict and the reason. Rejections always carry one. */
  onAnswer: (approve: boolean, action: Action, reason: string) => void;
  /** An answer in flight, or the refusal the last one drew. */
  busy?: boolean;
  error?: string | null;
}

export function ApprovalCard({
  approval,
  onAnswer,
  busy = false,
  error = null,
}: ApprovalCardProps): JSX.Element {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const action = approval.action;

  return (
    <li className="rounded border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-medium">
          {action ? `${action.operation} — approval required` : `Action ${approval.action_id}`}
        </h2>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          expires {approval.expires_at}
        </span>
      </div>

      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Proposed by {approval.proposed_by} · {approval.rule}
        {approval.because ? `: ${approval.because}` : ""}
      </p>

      {action ? <ActionDetail action={action} /> : null}

      {error && <p className="mt-3 text-sm text-red-700 dark:text-red-400">{error}</p>}

      {action === null ? (
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
          This request has no recorded Action, so there is nothing to read and it cannot be answered
          here.
        </p>
      ) : rejecting ? (
        <div className="mt-3">
          <label className="text-xs text-slate-500 dark:text-slate-400" htmlFor="reason">
            Why not? The proposer reads this first.
          </label>
          <textarea
            id="reason"
            className="mt-1 w-full rounded border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="rounded bg-red-700 px-3 py-1 text-sm text-white disabled:opacity-50"
              // Disabled on an empty reason rather than sending one. See the
              // module docstring: "no" with no reason tells the proposer
              // nothing about what to change.
              disabled={busy || reason.trim() === ""}
              onClick={() => onAnswer(false, action, reason.trim())}
            >
              Confirm rejection
            </button>
            <button
              type="button"
              className="rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700"
              onClick={() => setRejecting(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="rounded bg-emerald-700 px-3 py-1 text-sm text-white disabled:opacity-50"
            disabled={busy}
            onClick={() => onAnswer(true, action, "")}
          >
            Approve
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700"
            disabled={busy}
            onClick={() => setRejecting(true)}
          >
            Reject
          </button>
        </div>
      )}
    </li>
  );
}
