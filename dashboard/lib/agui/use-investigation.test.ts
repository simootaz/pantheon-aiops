/**
 * Which AG-UI events change run state, and which are none of this hook's business.
 *
 * Phase: 4 - Delivery Flow
 */
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ALLOWED_COMPONENTS } from "@/components/a2ui/allowlist";
import type { Investigation } from "@/types/generated/contracts";
import { InvestigationStore } from "./investigation-state";
import { COMPONENTS_HEADER } from "./stream";
import { applyEvent, isTerminal, useInvestigation } from "./use-investigation";

function baseInvestigation(): Investigation {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    state: "running",
    trigger: { kind: "alert", received_at: "2026-08-15T00:00:00Z", source: "alertmanager" },
    created_at: "2026-08-15T00:00:00Z",
    findings: [],
    resolutions: [],
    audit: [],
  } as unknown as Investigation;
}

describe("applyEvent", () => {
  it("takes the whole Investigation from a snapshot", () => {
    const store = new InvestigationStore();

    expect(applyEvent(store, { type: "STATE_SNAPSHOT", snapshot: baseInvestigation() })).toBe(true);
    expect(store.current()?.id).toBe("00000000-0000-0000-0000-000000000001");
  });

  it("applies a delta in order", () => {
    const store = new InvestigationStore();
    applyEvent(store, { type: "STATE_SNAPSHOT", snapshot: baseInvestigation() });

    applyEvent(store, {
      type: "STATE_DELTA",
      delta: [{ op: "add", path: "/findings/-", value: { title: "pool exhausted" } }],
    });

    expect(store.current()?.findings).toHaveLength(1);
  });

  it("ignores an event carrying no run state rather than failing on it", () => {
    // The stream is allowed to say more than this hook reads. A view that threw
    // on an unrecognised event would break the moment the protocol gained one.
    const store = new InvestigationStore();

    expect(applyEvent(store, { type: "STEP_STARTED" })).toBe(false);
    expect(applyEvent(store, { type: "CUSTOM" })).toBe(false);
  });

  it("refuses a delta that arrives before a snapshot", () => {
    // Turns "the server changed its opening sequence" into an error rather than
    // a quietly wrong screen.
    const store = new InvestigationStore();

    expect(() =>
      applyEvent(store, {
        type: "STATE_DELTA",
        delta: [{ op: "add", path: "/findings/-", value: {} }],
      }),
    ).toThrow(/before StateSnapshot/);
  });

  it("treats a snapshot as replacing everything, not merging", () => {
    // A reconnect opens with a snapshot, and merging it into old state is how a
    // client ends up showing a run that never happened.
    const store = new InvestigationStore();
    applyEvent(store, { type: "STATE_SNAPSHOT", snapshot: baseInvestigation() });
    applyEvent(store, {
      type: "STATE_DELTA",
      delta: [{ op: "add", path: "/findings/-", value: { title: "one" } }],
    });

    applyEvent(store, { type: "STATE_SNAPSHOT", snapshot: baseInvestigation() });

    expect(store.current()?.findings).toHaveLength(0);
  });
});

describe("isTerminal", () => {
  it("ends on a finished run and on an errored one", () => {
    expect(isTerminal({ type: "RUN_FINISHED" })).toBe(true);
    expect(isTerminal({ type: "RUN_ERROR" })).toBe(true);
  });

  it("does not end on anything else", () => {
    // A stream closed early is a client that stops seeing the rest of the run.
    expect(isTerminal({ type: "STEP_FINISHED" })).toBe(false);
    expect(isTerminal({ type: "STATE_DELTA" })).toBe(false);
  });
});

describe("the stream the hook opens", () => {
  it("declares the renderer's full catalog, so the server can check it", async () => {
    // `stream.test.ts` proves `readStream` sends a catalog it is given. This
    // proves the hook gives it one. Without it, a hook that stopped passing
    // `components` would stream every run as "undeclared" and never be refused
    // over an approval prompt it could not draw.
    const seen: Headers[] = [];
    vi.stubGlobal("fetch", (input: string, init?: RequestInit) => {
      seen.push(new Request(input, init).headers);
      // Never resolves: the test is about the request, not the response, and
      // an answered stream would start the reconnect timer.
      return new Promise<Response>(() => {});
    });

    const { unmount } = renderHook(() => useInvestigation("run-1", "token"));
    await waitFor(() => expect(seen).toHaveLength(1));

    expect(seen[0]?.get(COMPONENTS_HEADER)).toBe(ALLOWED_COMPONENTS.join(","));

    unmount();
    vi.unstubAllGlobals();
  });
});
