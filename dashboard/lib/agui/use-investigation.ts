/**
 * The Investigation, live, as a React hook.
 *
 * One AG-UI stream in, one Investigation out. `StateSnapshot` replaces
 * everything; `StateDelta` applies RFC 6902 patches in order. That is the whole
 * protocol for run state - see `investigation-state.ts`.
 *
 * A RECONNECT STARTS FROM A NEW SNAPSHOT, NEVER FROM THE OLD STATE
 * ----------------------------------------------------------------
 * The server opens every stream with a snapshot. Keeping the previous
 * Investigation across a reconnect and applying the new stream's patches to it
 * would produce a run that never happened - findings listed twice, or a verdict
 * from before a retry.
 *
 * So the store is rebuilt on connect. `InvestigationStore` separately refuses a
 * delta that arrives before a snapshot, which turns "the server changed its
 * opening sequence" into an error rather than a quietly wrong screen.
 *
 * WHAT `connected` MEANS, AND WHY `error` IS SEPARATE
 * ---------------------------------------------------
 * `connected` is whether a stream is open. `error` is why the last one closed.
 * A view that had only one flag could not tell "reconnecting after a blip" from
 * "your token was rejected" - and those are a spinner and a login prompt.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { useEffect, useRef, useState } from "react";
import type { Investigation } from "@/types/generated/contracts";
import { InvestigationStore, type JsonPatchOperation } from "./investigation-state";
import { backoffMs, isRetryable, readStream, StreamError } from "./stream";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** What a view gets back. */
export interface InvestigationStream {
  investigation: Investigation | null;
  connected: boolean;
  /** Why the last stream closed, or `null`. Separate from `connected`. */
  error: string | null;
  /** True once a stream failed in a way retrying cannot fix. */
  fatal: boolean;
}

/** The AG-UI event shapes this hook acts on. Everything else is ignored. */
interface AguiEvent {
  type?: string;
  snapshot?: Investigation;
  delta?: JsonPatchOperation[];
}

/**
 * Apply one AG-UI event to the store. Returns whether the state changed.
 *
 * Exported so it can be tested without React. The interesting logic is which
 * events change state and which do not, and that is not worth a rendered
 * component to assert.
 */
export function applyEvent(store: InvestigationStore, event: AguiEvent): boolean {
  if (event.type === "STATE_SNAPSHOT" && event.snapshot) {
    store.snapshot(event.snapshot);
    return true;
  }
  if (event.type === "STATE_DELTA" && event.delta) {
    store.delta(event.delta);
    return true;
  }
  // RunStarted, StepStarted, Custom and the rest carry no run state. Ignored
  // rather than treated as an error: the stream is allowed to say more than
  // this hook reads, and a view that threw on an unrecognised event would
  // break the moment the protocol gained one.
  return false;
}

/** Whether this event ends the run, and so the stream. */
export function isTerminal(event: AguiEvent): boolean {
  return event.type === "RUN_FINISHED" || event.type === "RUN_ERROR";
}

/**
 * Subscribe to one investigation.
 *
 * `token` is passed rather than read from storage here: a hook that reached for
 * a credential itself would be a second place credentials are looked up, and
 * the app's session is the one place that should know.
 */
export function useInvestigation(
  investigationId: string | null,
  token?: string,
): InvestigationStream {
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState(false);
  const attempts = useRef(0);

  useEffect(() => {
    if (!investigationId) return;

    const controller = new AbortController();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function connect(): Promise<void> {
      // A NEW store per connection. See the module docstring: patches from a
      // fresh stream applied to old state produce a run that never happened.
      const store = new InvestigationStore();

      try {
        setError(null);
        for await (const raw of readStream({
          url: `${API_URL}/agui/${investigationId}`,
          token,
          signal: controller.signal,
        })) {
          if (cancelled) return;
          const event = raw as AguiEvent;

          setConnected(true);
          attempts.current = 0;

          if (applyEvent(store, event)) {
            setInvestigation(store.current());
          }
          if (isTerminal(event)) {
            setConnected(false);
            return; // the run ended; there is nothing further to wait for
          }
        }
        // The stream closed without a terminal event - a proxy timeout, or a
        // restart. Retried, because the run may still be going.
        if (!cancelled) schedule();
      } catch (caught) {
        if (cancelled) return;
        setConnected(false);
        setError(caught instanceof Error ? caught.message : String(caught));

        if (isRetryable(caught)) {
          schedule();
        } else {
          // A 401, 403 or 404. Retrying produces a log full of failures and
          // never a connection, so the view is told to stop waiting.
          setFatal(true);
        }
      }
    }

    function schedule(): void {
      attempts.current += 1;
      timer = setTimeout(() => {
        if (!cancelled) void connect();
      }, backoffMs(attempts.current));
    }

    void connect();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [investigationId, token]);

  return { investigation, connected, error, fatal };
}

export { StreamError };
