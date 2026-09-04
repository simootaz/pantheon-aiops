/**
 * One investigation, live.
 *
 * Subscribes to the AG-UI stream: `StateSnapshot` at open, `StateDelta`
 * thereafter. The Investigation is the shared state object and this renders it -
 * there is no second source of truth on this page.
 *
 * `connected` AND `error` ARE BOTH SHOWN
 * --------------------------------------
 * A run that finished and a stream that dropped both stop producing events. One
 * is done and one needs a retry, and a single "live" dot cannot tell a reader
 * which they are looking at.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { use } from "react";
import { FindingRow, Gaps, Status } from "@/components/investigations";
import { Loading, Refused, SignedOut } from "@/components/states";
import { useInvestigation } from "@/lib/agui/use-investigation";
import { headline } from "@/lib/investigations";
import { useToken } from "@/lib/session";

export default function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { token, ready } = useToken();
  // `null` until the session has been read: opening a stream without the token
  // would draw a 401, mark the view fatal, and never retry once it arrived.
  const { investigation, connected, error, fatal } = useInvestigation(
    ready && token ? id : null,
    token ?? undefined,
  );

  if (!ready) return <Loading what="session" />;
  if (!token) return <SignedOut />;
  if (fatal && error) return <Refused message={error} />;
  if (!investigation) return <Loading what="the investigation" />;

  return (
    <section>
      <div className="flex items-baseline gap-3">
        <h1 className="text-2xl font-semibold">{headline(investigation)}</h1>
        <Status investigation={investigation} connected={connected} fatal={fatal} />
      </div>

      {/* Shown even while connected: a drop that recovered is still worth
          seeing, because it explains a gap in the timeline. */}
      {error && !fatal && (
        <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">{error}</p>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-slate-500 dark:text-slate-400">State</dt>
          <dd>{investigation.state}</dd>
        </div>
        <div>
          <dt className="text-slate-500 dark:text-slate-400">Findings</dt>
          <dd>{investigation.findings?.length ?? 0}</dd>
        </div>
        <div>
          <dt className="text-slate-500 dark:text-slate-400">Hypotheses</dt>
          <dd>{investigation.hypotheses?.length ?? 0}</dd>
        </div>
        <div>
          <dt className="text-slate-500 dark:text-slate-400">Confidence</dt>
          {/* 0 is rendered, not hidden. `??` rather than `||` for exactly that:
              a confidence of 0 is the aggregator saying it has no leading
              hypothesis - see core/orchestrator/hypotheses.py - and `||` would
              turn that conclusion into an em dash meaning "not decided yet". */}
          <dd>{investigation.verdict?.confidence ?? "—"}</dd>
        </div>
      </dl>

      <Gaps investigation={investigation} />

      {investigation.verdict && (
        <p className="mt-4 rounded border border-slate-200 p-4 text-sm dark:border-slate-800">
          {investigation.verdict.summary}
        </p>
      )}

      <h2 className="mt-6 text-lg font-semibold">Findings</h2>
      <ul className="mt-2">
        {(investigation.findings ?? []).map((finding) => (
          <FindingRow key={finding.id} finding={finding} />
        ))}
      </ul>
    </section>
  );
}
