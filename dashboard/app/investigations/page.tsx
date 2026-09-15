/**
 * Investigations.
 *
 * Recent runs, newest first, narrowed by the server to this token's tenant.
 * Opening one subscribes to its AG-UI stream - see `[id]/page.tsx`.
 *
 * WHY THIS LIST IS A REST READ AND NOT A STREAM
 * ---------------------------------------------
 * A stream is about one investigation and starts when you open it. "What ran in
 * the last hour" is a question about runs that finished before this tab
 * existed, and no stream can answer it.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { useEffect, useState } from "react";
import { Row } from "@/components/investigations";
import { Empty, Loading, Refused, SignedOut } from "@/components/states";
import { ApiError, recentInvestigations } from "@/lib/api";
import { useToken } from "@/lib/session";
import type { Investigation } from "@/types/generated/contracts";

export default function InvestigationsPage() {
  const { token, ready } = useToken();
  const [runs, setRuns] = useState<Investigation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;

    recentInvestigations(token)
      .then((found) => {
        if (!cancelled) setRuns(found);
      })
      .catch((caught: unknown) => {
        // A refusal becomes an error, never an empty list. See `lib/api.ts`.
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : String(caught));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token, ready]);

  return (
    <section>
      <h1 className="text-2xl font-semibold">Investigations</h1>
      <div className="mt-4">
        {!ready ? (
          <Loading what="session" />
        ) : !token ? (
          <SignedOut />
        ) : error ? (
          <Refused message={error} />
        ) : runs === null ? (
          <Loading what="investigations" />
        ) : runs.length === 0 ? (
          <Empty what="investigations" />
        ) : (
          <ul>
            {runs.map((run) => (
              <Row key={run.id} investigation={run} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
