/**
 * Approvals.
 *
 * The human-in-the-loop queue: every Action a policy rule sent to a person,
 * oldest first, each rendered with what the approval card carries rather than
 * with an id. There is no second inbox - this and the A2UI surface are two
 * renderings of the same request in `core/guardrails/approval_gate.py`.
 *
 * AN ANSWERED REQUEST LEAVES THE LIST
 * -----------------------------------
 * `gate.pending()` returns only what is still waiting, so a refetch after an
 * answer is what removes the row. Removing it optimistically would hide a
 * refusal: the gate can reject an answer - already answered, expired, the
 * proposer approving their own Action - and the row vanishing would read as
 * success. It refetches instead.
 *
 * WHY THE QUEUE IS EMPTY TODAY
 * ----------------------------
 * Nothing opens a request yet. `open_request` has no production caller: the
 * executor refuses an Action needing approval when none was supplied, and no
 * code path turns that refusal into somebody being asked. This view is correct
 * and will stay empty until that link exists - which is a gap in the flow, not
 * in this page, and is recorded as one in the repository map.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { ApprovalCard } from "@/components/approvals";
import { Empty, Loading, Refused, SignedOut } from "@/components/states";
import { ApiError, type PendingApproval, pendingApprovals, respondToApproval } from "@/lib/api";
import { useToken } from "@/lib/session";
import type { Action } from "@/types/generated/contracts";

export default function ApprovalsPage() {
  const { token, ready } = useToken();
  const [waiting, setWaiting] = useState<PendingApproval[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answering, setAnswering] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<Record<string, string>>({});

  const load = useCallback(async (): Promise<void> => {
    if (!token) return;
    try {
      setWaiting(await pendingApprovals(token));
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [token]);

  useEffect(() => {
    if (!ready || !token) return;
    void load();
  }, [ready, token, load]);

  async function answer(
    request: PendingApproval,
    approve: boolean,
    action: Action,
    reason: string,
  ): Promise<void> {
    setAnswering(request.id);
    setRefusal((previous) => ({ ...previous, [request.id]: "" }));
    try {
      await respondToApproval(request.id, approve, action, reason, token);
      await load();
    } catch (caught: unknown) {
      // A 409 is the gate saying no, and it is the interesting case: already
      // answered, expired, or the proposer answering their own request. Shown
      // on the card rather than as a page-level error, because the other rows
      // are still answerable.
      setRefusal((previous) => ({
        ...previous,
        [request.id]: caught instanceof ApiError ? caught.message : String(caught),
      }));
    } finally {
      setAnswering(null);
    }
  }

  return (
    <section>
      <h1 className="text-2xl font-semibold">Approvals</h1>
      <div className="mt-4">
        {!ready ? (
          <Loading what="session" />
        ) : !token ? (
          <SignedOut />
        ) : error ? (
          <Refused message={error} />
        ) : waiting === null ? (
          <Loading what="the approval queue" />
        ) : waiting.length === 0 ? (
          <Empty what="approvals waiting" />
        ) : (
          <ul className="grid gap-3">
            {waiting.map((request) => (
              <ApprovalCard
                key={request.id}
                approval={request}
                busy={answering === request.id}
                error={refusal[request.id] || null}
                onAnswer={(approve, action, reason) => {
                  void answer(request, approve, action, reason);
                }}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
