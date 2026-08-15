/**
 * AG-UI client: the dashboard's only channel to Pantheon.
 *
 * Replaces the bespoke WebSocket layer that used to live in api/ws/. Every
 * frontend interaction is a typed AG-UI event over SSE, so this client is a
 * thin arrangement of `@ag-ui/client` rather than a protocol implementation.
 *
 * Capability negotiation is Pantheon convention, not specification: A2UI puts
 * `a2uiClientCapabilities` in A2A message metadata and AG-UI defines no analog,
 * so we send ours in the run input at run start. It is sourced from the
 * generated allowlist, which means what we advertise is exactly what the
 * renderer accepts.
 *
 * See docs/adr/0006-agentic-ui-protocols.md.
 *
 * Phase: 4 - Delivery Flow
 */
import { HttpAgent, type RunAgentParameters } from "@ag-ui/client";
import { ALLOWED_COMPONENTS } from "@/components/a2ui/allowlist";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** A2UI version Pantheon implements. v1.0 is still a release candidate. */
export const A2UI_VERSION = "v0.9.1";

/** Identifier for Pantheon's closed component catalog. */
export const PANTHEON_CATALOG_ID = "pantheon.v1";

/**
 * What this client can render, declared once at run start.
 *
 * Built from ALLOWED_COMPONENTS rather than restated, so the allowlist, the
 * renderer and the advertised capabilities stay one artifact.
 */
export function clientCapabilities() {
  return {
    catalog_id: PANTHEON_CATALOG_ID,
    a2ui_version: A2UI_VERSION,
    components: [...ALLOWED_COMPONENTS],
  };
}

/** Build an agent bound to Pantheon's AG-UI endpoint. */
export function createPantheonAgent(investigationId?: string): HttpAgent {
  return new HttpAgent({
    url: `${API_URL}/agui`,
    headers: { "content-type": "application/json" },
    ...(investigationId ? { threadId: investigationId } : {}),
  });
}

/**
 * Parameters for a run, carrying the client's capabilities.
 *
 * `forwardedProps` belongs to `runAgent()` rather than the constructor - a
 * detail worth stating, because capabilities are genuinely per-run: a client
 * that upgrades mid-session declares the new set on its next run without
 * rebuilding the agent.
 */
export function runParameters(): RunAgentParameters {
  return {
    forwardedProps: {
      a2uiClientCapabilities: clientCapabilities(),
    },
  };
}

/**
 * Start a run with capabilities attached.
 *
 * The backend therefore knows what this renderer accepts before an agent emits
 * anything, and never generates a component that would be rejected.
 */
export function startRun(agent: HttpAgent) {
  return agent.runAgent(runParameters());
}

// TODO: Phase 4 - add reconnection and auth middleware
