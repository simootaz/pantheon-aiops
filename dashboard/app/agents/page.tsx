/**
 * Agents.
 *
 * The roster from `core.registry`, each row saying whether it is live, written
 * but unreachable, or a manifest with nothing behind it. Read-only: an agent is
 * enabled by registering it, not by a toggle here.
 *
 * NO TOKEN GUARD, DELIBERATELY
 * ----------------------------
 * `GET /agents` takes no principal - it is the roster of what the platform is,
 * not of what happened to anyone. Every other view refuses without a token
 * because the data belongs to a tenant; this one has nothing to narrow, and a
 * sign-in prompt in front of it would be a claim that it did.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { useEffect, useState } from "react";
import { AgentRow } from "@/components/agents";
import { Empty, Loading, Refused } from "@/components/states";
import { type AgentSummary, ApiError, agents } from "@/lib/api";
import { useToken } from "@/lib/session";

export default function AgentsPage() {
  const { token, ready } = useToken();
  const [roster, setRoster] = useState<AgentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;

    // The token is passed when there is one and the request goes out either
    // way. Sending it costs nothing and keeps one code path; withholding it
    // would make this the only read whose behaviour depends on the session.
    agents(token)
      .then((found) => {
        if (!cancelled) setRoster(found);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : String(caught));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  return (
    <section>
      <h1 className="text-2xl font-semibold">Agents</h1>
      <div className="mt-4">
        {!ready ? (
          <Loading what="session" />
        ) : error ? (
          <Refused message={error} />
        ) : roster === null ? (
          <Loading what="the roster" />
        ) : roster.length === 0 ? (
          <Empty what="agents on the roster" />
        ) : (
          <ul>
            {roster.map((agent) => (
              <AgentRow key={agent.codename} agent={agent} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
