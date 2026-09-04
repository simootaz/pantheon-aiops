/**
 * What the investigation views must say out loud.
 *
 * Rendered rather than reasoned about, because the failure being guarded is a
 * rendering one: a partial run that looks whole, or a finished run that looks
 * like it is still reconnecting. Both are readable only from the output.
 *
 * Phase: 4 - Delivery Flow
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Finding, Investigation, InvestigationState } from "@/types/generated/contracts";
import { Gaps, Row, Status } from "./investigations";

function finding(kind: Finding["kind"], overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f1",
    agent: "lethe",
    title: "lease expired before the log search ran",
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
    state: "running",
    trigger: {
      kind: "alert",
      source: "prometheus",
      received_at: "2026-09-04T09:58:00Z",
      title: "checkout pods restarting",
    },
    findings: [],
    ...overrides,
  } as Investigation;
}

describe("Row", () => {
  it("marks a run partial when a step could not run", () => {
    render(
      <ul>
        <Row investigation={investigation({ findings: [finding("degraded")] })} />
      </ul>,
    );

    expect(screen.getByText("partial")).toBeDefined();
  });

  it("does not mark a whole run partial", () => {
    // The control. A row that said "partial" always would tell a reader
    // nothing, and they would learn to ignore the word.
    render(
      <ul>
        <Row investigation={investigation({ findings: [finding("anomaly")] })} />
      </ul>,
    );

    expect(screen.queryByText("partial")).toBeNull();
  });

  it("links to the run by id, not by title", () => {
    // Titles are not unique and come from an alert payload. The link must be
    // the id or two different incidents share a URL.
    render(
      <ul>
        <Row investigation={investigation()} />
      </ul>,
    );

    expect(screen.getByRole("link").getAttribute("href")).toBe(
      "/investigations/11111111-1111-1111-1111-111111111111",
    );
  });
});

describe("Status", () => {
  it("says finished for a completed run whose stream has closed", () => {
    // The bug this exists to prevent: reading `connected` alone leaves every
    // completed investigation claiming to be reconnecting forever.
    render(
      <Status
        investigation={investigation({ state: "completed" as InvestigationState })}
        connected={false}
        fatal={false}
      />,
    );

    expect(screen.getByText("finished")).toBeDefined();
  });

  it("says reconnecting for a running one whose stream dropped", () => {
    render(
      <Status
        investigation={investigation({ state: "running" as InvestigationState })}
        connected={false}
        fatal={false}
      />,
    );

    expect(screen.getByText("reconnecting")).toBeDefined();
  });

  it("says live while a running one is connected", () => {
    render(<Status investigation={investigation()} connected={true} fatal={false} />);

    expect(screen.getByText("live")).toBeDefined();
  });

  it("says stopped when retrying cannot help, even for a running run", () => {
    // A rejected token on a run that is still going. "Reconnecting" here would
    // be a lie the reader waits on.
    render(<Status investigation={investigation()} connected={false} fatal={true} />);

    expect(screen.getByText("stopped")).toBeDefined();
  });
});

describe("Gaps", () => {
  it("names the agent and what it could not do", () => {
    render(<Gaps investigation={investigation({ findings: [finding("degraded")] })} />);

    expect(screen.getByText(/lethe/)).toBeDefined();
    expect(screen.getByText(/lease expired/)).toBeDefined();
  });

  it("renders nothing for a whole run", () => {
    const { container } = render(
      <Gaps investigation={investigation({ findings: [finding("observation")] })} />,
    );

    expect(container.textContent).toBe("");
  });

  it("counts steps, not findings, in the singular and the plural", () => {
    const { rerender } = render(
      <Gaps investigation={investigation({ findings: [finding("degraded")] })} />,
    );
    expect(screen.getByText(/1 step could not run/)).toBeDefined();

    rerender(
      <Gaps
        investigation={investigation({
          findings: [finding("degraded"), finding("degraded", { id: "f2", agent: "argus" })],
        })}
      />,
    );
    expect(screen.getByText(/2 steps could not run/)).toBeDefined();
  });
});
