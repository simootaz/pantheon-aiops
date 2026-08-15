/**
 * StateSnapshot then StateDelta over the Investigation.
 *
 * Phase: 4 - Delivery Flow
 */
import { describe, expect, it } from "vitest";
import type { Investigation } from "@/types/generated/contracts";
import { applyPatch, InvestigationStore } from "./investigation-state";

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

describe("applyPatch", () => {
  it("appends to an array with the RFC 6902 '-' index", () => {
    const next = applyPatch(baseInvestigation(), [
      { op: "add", path: "/findings/-", value: { title: "pool exhausted" } },
    ]);
    expect(next.findings).toHaveLength(1);
  });

  it("replaces a scalar", () => {
    const next = applyPatch(baseInvestigation(), [
      { op: "replace", path: "/state", value: "completed" },
    ]);
    expect(next.state).toBe("completed");
  });

  it("does not mutate the previous state, so React re-renders", () => {
    const before = baseInvestigation();
    const after = applyPatch(before, [{ op: "add", path: "/findings/-", value: { title: "x" } }]);
    expect(before.findings).toHaveLength(0);
    expect(after).not.toBe(before);
  });

  it("decodes escaped pointer tokens", () => {
    const next = applyPatch({ "a/b": 1 } as Record<string, unknown>, [
      { op: "replace", path: "/a~1b", value: 2 },
    ]);
    expect(next["a/b"]).toBe(2);
  });

  it("throws on an unsupported op rather than desynchronising quietly", () => {
    expect(() =>
      applyPatch(baseInvestigation(), [{ op: "move", path: "/state", from: "/id" }]),
    ).toThrow(/unsupported/);
  });
});

describe("InvestigationStore", () => {
  it("refuses a delta before a snapshot", () => {
    const store = new InvestigationStore();
    expect(() => store.delta([{ op: "replace", path: "/state", value: "failed" }])).toThrow(
      /before StateSnapshot/,
    );
  });

  it("applies snapshot then deltas in order", () => {
    const store = new InvestigationStore();
    store.snapshot(baseInvestigation());
    store.delta([{ op: "add", path: "/findings/-", value: { title: "one" } }]);
    store.delta([{ op: "replace", path: "/state", value: "completed" }]);

    const current = store.current();
    expect(current?.findings).toHaveLength(1);
    expect(current?.state).toBe("completed");
  });
});
