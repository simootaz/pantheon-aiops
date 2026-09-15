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
import { Gaps, Row, Status, Timeline } from "./investigations";

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

describe("Timeline", () => {
  it("renders entries in the order the server sent them, not re-sorted", () => {
    // The server keeps ties in record order: steps before findings. Two
    // entries at one second whose kinds sort the OTHER way alphabetically, so
    // a client that re-sorted - by timestamp, then by anything - would swap
    // them. A plant that sorted by timestamp then kind passed a fixture where
    // the alphabet happened to agree with the server.
    const { container } = render(
      <Timeline
        entries={[
          {
            at: "2026-09-15T10:00:12Z",
            kind: "step_started",
            actor: "lethe",
            summary: "lethe dispatched",
            ref: null,
          },
          {
            at: "2026-09-15T10:00:12Z",
            kind: "finding",
            actor: "argus",
            summary: "argus reported anomaly",
            ref: "f1",
          },
        ]}
      />,
    );

    const items = Array.from(container.querySelectorAll("li")).map((li) => li.textContent ?? "");
    expect(items[0]).toContain("lethe dispatched");
    expect(items[1]).toContain("argus reported anomaly");
  });

  it("renders nothing for a run with no entries yet", () => {
    const { container } = render(<Timeline entries={[]} />);

    expect(container.textContent).toBe("");
  });

  it("marks a degraded step so a partial run is visibly partial", () => {
    render(
      <Timeline
        entries={[
          {
            at: "2026-09-15T10:00:15Z",
            kind: "degraded",
            actor: "lethe",
            summary: "lethe could not look: no lease",
            ref: "f2",
          },
        ]}
      />,
    );

    expect(screen.getByText(/could not look/).className).toContain("amber");
  });
});

describe("Status, waiting", () => {
  it("says waiting for approval rather than live", () => {
    // The stream is open and idle on purpose. "live" would say the agents are
    // working; the run is waiting for a person, possibly the one reading this.
    render(
      <Status
        investigation={investigation({ state: "awaiting_approval" as InvestigationState })}
        connected={true}
        fatal={false}
      />,
    );

    expect(screen.getByText("waiting for approval")).toBeDefined();
    expect(screen.queryByText("live")).toBeNull();
  });
});
