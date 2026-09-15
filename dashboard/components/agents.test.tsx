/**
 * The roster's three states, and the one that used to be invisible.
 *
 * Themis is written, tooled and tested, and no trigger routes to it. On a
 * single `implemented` field it rendered exactly as Clio does - and Clio is a
 * manifest with nothing behind it. A reader was told an agent that runs does
 * not exist.
 *
 * Phase: 4 - Delivery Flow
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentSummary } from "@/lib/api";
import { AgentRow, standingOf } from "./agents";

function agent(overrides: Partial<AgentSummary> = {}): AgentSummary {
  return {
    codename: "argus",
    domain: "anomaly",
    description: "detects anomalies in metric series",
    capabilities: ["metric_anomaly"],
    tools: ["prometheus.query_range"],
    implemented: true,
    dispatchable: true,
    ...overrides,
  };
}

describe("standingOf", () => {
  it("separates written-and-unreachable from not written", () => {
    // The whole reason the second field exists. If these two collapsed to one
    // answer the roster would be back where it started.
    const themis = agent({ codename: "themis", implemented: true, dispatchable: false });
    const clio = agent({ codename: "clio", implemented: false, dispatchable: false });

    expect(standingOf(themis)).toBe("not-routed");
    expect(standingOf(clio)).toBe("declared");
    expect(standingOf(themis)).not.toBe(standingOf(clio));
  });

  it("calls an implemented, routable agent live", () => {
    // The control. A function that answered "not-routed" for everything would
    // pass the assertions above.
    expect(standingOf(agent())).toBe("live");
  });

  it("reads the impossible fourth case as the weaker claim", () => {
    // Dispatchable without an implementation cannot happen - `register` writes
    // both registries and the API asserts it - but if it ever did, claiming
    // less is the safe way to be wrong.
    expect(standingOf(agent({ implemented: false, dispatchable: true }))).toBe("declared");
  });
});

describe("AgentRow", () => {
  it("says what a standing means rather than only colouring it", () => {
    // A reader who does not already know the difference between Live and Not
    // routed learns it here instead of guessing from an amber dot.
    render(
      <ul>
        <AgentRow agent={agent({ codename: "themis", dispatchable: false })} />
      </ul>,
    );

    expect(screen.getByText("Not routed")).toBeDefined();
    expect(screen.getByText(/nothing produces a plan that names it/)).toBeDefined();
  });

  it("does not describe an unreachable agent as unbuilt", () => {
    // The specific wrong sentence. "No implementation" said of Themis is false.
    render(
      <ul>
        <AgentRow agent={agent({ codename: "themis", dispatchable: false })} />
      </ul>,
    );

    expect(screen.queryByText(/no implementation behind it/)).toBeNull();
  });

  it("does describe a manifest-only agent as unbuilt", () => {
    // The control on the previous test, and the sentence that is true of Clio.
    render(
      <ul>
        <AgentRow agent={agent({ codename: "clio", implemented: false, dispatchable: false })} />
      </ul>,
    );

    expect(screen.getByText(/no implementation behind it/)).toBeDefined();
  });

  it("lists the tool allowlist, which is what the agent may call", () => {
    render(
      <ul>
        <AgentRow agent={agent({ tools: ["prometheus.query_range", "prometheus.series"] })} />
      </ul>,
    );

    expect(screen.getByText(/prometheus.query_range, prometheus.series/)).toBeDefined();
  });

  it("omits the tool line entirely for an agent that declares none", () => {
    // Clio declares no tools. "Tools:" followed by nothing reads as a failed
    // load rather than as an agent that calls nothing.
    render(
      <ul>
        <AgentRow agent={agent({ codename: "clio", tools: [] })} />
      </ul>,
    );

    expect(screen.queryByText(/Tools:/)).toBeNull();
  });
});
