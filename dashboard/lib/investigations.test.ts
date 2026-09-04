/**
 * What "partial" means, asserted against the thing rather than against a flag.
 *
 * The test that matters is the one where a DEGRADED finding is present and the
 * run is otherwise a clean success. A dashboard that reported partiality from a
 * status field, or from a findings count, would call that run whole - and a
 * reader would act on a verdict drawn from evidence half of which was never
 * collected.
 *
 * Phase: 4 - Delivery Flow
 */
import { describe, expect, it } from "vitest";
import type { Finding, Investigation, InvestigationState } from "@/types/generated/contracts";
import { degraded, headline, isPartial, isTerminal } from "./investigations";

function finding(kind: Finding["kind"], overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f1",
    agent: "lethe",
    title: "log search never ran",
    severity: "medium",
    confidence: 0.9,
    detected_at: "2026-09-04T10:00:00Z",
    kind,
    ...overrides,
  } as Finding;
}

function investigation(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    created_at: "2026-09-04T09:59:00Z",
    state: "completed",
    trigger: { kind: "alert", source: "prometheus", received_at: "2026-09-04T09:58:00Z" },
    findings: [],
    ...overrides,
  } as Investigation;
}

describe("isPartial", () => {
  it("is true when an agent reported that it could not do its job", () => {
    const run = investigation({
      findings: [finding("anomaly"), finding("degraded", { id: "f2" })],
    });

    expect(isPartial(run)).toBe(true);
  });

  it("is false for a run whose agents all reported", () => {
    // The control. A check that answered true for everything would put an
    // amber "partial" on every row, which is the same as putting it on none.
    const run = investigation({
      findings: [finding("anomaly"), finding("correlation", { id: "f2" })],
    });

    expect(isPartial(run)).toBe(false);
  });

  it("is false for a run with no findings at all", () => {
    // "Nobody found anything" is not "nobody looked". A quiet system is a
    // legitimate outcome and must not be dressed up as a broken run.
    expect(isPartial(investigation({ findings: [] }))).toBe(false);
    expect(isPartial(investigation({ findings: undefined }))).toBe(false);
  });

  it("does not read partiality off the run state", () => {
    // A run can complete cleanly and still be partial: Zeus finishes, Lethe's
    // lease expired an hour earlier. `state` says the orchestrator stopped, and
    // nothing about whether every step got to run.
    const run = investigation({
      state: "completed" as InvestigationState,
      findings: [finding("degraded")],
    });

    expect(run.state).toBe("completed");
    expect(isPartial(run)).toBe(true);
  });
});

describe("degraded", () => {
  it("returns the gaps themselves, so a view can name what is missing", () => {
    // A count would say "1 step could not run". The finding says which agent
    // and why, and that is what tells a reader whether the verdict is usable.
    const gaps = degraded(
      investigation({
        findings: [finding("observation"), finding("degraded", { id: "f2", agent: "argus" })],
      }),
    );

    expect(gaps).toHaveLength(1);
    expect(gaps[0]?.agent).toBe("argus");
  });
});

describe("isTerminal", () => {
  it("counts failed and cancelled, not only completed", () => {
    // A cancelled run is over. Treating only `completed` as terminal would
    // leave the detail view claiming to reconnect to a stream nobody will
    // ever write to again.
    for (const state of ["completed", "failed", "cancelled"] as InvestigationState[]) {
      expect(isTerminal(investigation({ state }))).toBe(true);
    }
  });

  it("does not count a run still in flight", () => {
    for (const state of [
      "pending",
      "planning",
      "running",
      "awaiting_approval",
    ] as InvestigationState[]) {
      expect(isTerminal(investigation({ state }))).toBe(false);
    }
  });
});

describe("headline", () => {
  it("prefers the trigger's title", () => {
    const run = investigation({
      trigger: {
        kind: "alert",
        source: "prometheus",
        received_at: "2026-09-04T09:58:00Z",
        title: "checkout pods restarting",
      },
    });

    expect(headline(run)).toBe("checkout pods restarting");
  });

  it("falls back to the id rather than rendering nothing", () => {
    // A row with no visible text is a row nobody can click on purpose.
    expect(headline(investigation({ trigger: undefined }))).toBe(
      "11111111-1111-1111-1111-111111111111",
    );
  });

  it("treats a whitespace-only title as no title", () => {
    // A title of " " is not a headline; it is a blank link. `||` on a string
    // would not catch it, which is why the check is on `trim()`.
    const run = investigation({
      trigger: {
        kind: "alert",
        source: "prometheus",
        received_at: "2026-09-04T09:58:00Z",
        title: "   ",
      },
    });

    expect(headline(run)).toBe("11111111-1111-1111-1111-111111111111");
  });
});
