/**
 * The roster, and the three states an agent can be in.
 *
 * A manifest is not an implementation and an implementation is not a route. The
 * API says both facts because collapsing them told a reader that Themis - which
 * is written, tooled and tested - does not exist, exactly as it said of Clio,
 * which is a manifest and nothing else.
 *
 * So the row says which of the three it is, in words rather than a tick:
 *
 *   - **Live**: implemented and dispatchable. A trigger can reach it.
 *   - **Not routed**: implemented, not dispatchable. The code runs; nothing
 *     produces a plan that names it yet.
 *   - **Declared**: a manifest. Nothing behind it.
 *
 * Phase: 4 - Delivery Flow
 */
import type { JSX } from "react";
import type { AgentSummary } from "@/lib/api";

export type Standing = "live" | "not-routed" | "declared";

/**
 * Which of the three an agent is in.
 *
 * Dispatchable implies implemented - the API asserts it, and `register` writes
 * both registries - so the impossible fourth case is not represented. If it
 * ever arrived it would read as "not routed", which is the safe way to be
 * wrong: it claims less than the row would otherwise.
 */
export function standingOf(agent: AgentSummary): Standing {
  if (!agent.implemented) return "declared";
  return agent.dispatchable ? "live" : "not-routed";
}

const STANDING: Record<Standing, { label: string; detail: string; tone: string }> = {
  live: {
    label: "Live",
    detail: "a trigger can route to it",
    tone: "text-emerald-700 dark:text-emerald-400",
  },
  "not-routed": {
    label: "Not routed",
    detail: "implemented; nothing produces a plan that names it yet",
    tone: "text-amber-600 dark:text-amber-400",
  },
  declared: {
    label: "Declared",
    detail: "a manifest, with no implementation behind it",
    tone: "text-slate-500 dark:text-slate-400",
  },
};

export function AgentRow({ agent }: { agent: AgentSummary }): JSX.Element {
  const standing = STANDING[standingOf(agent)];

  return (
    <li className="border-b border-slate-200 py-3 last:border-0 dark:border-slate-800">
      <div className="flex items-baseline gap-3">
        <span className="font-medium">{agent.codename}</span>
        <span className="text-xs text-slate-500 dark:text-slate-400">{agent.domain}</span>
        <span className={`text-xs ${standing.tone}`}>{standing.label}</span>
      </div>

      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{agent.description}</p>

      {/* The standing spelled out, not just coloured. A reader who does not
          already know the difference between "Live" and "Not routed" learns it
          here rather than guessing from an amber dot. */}
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{standing.detail}</p>

      {agent.tools.length > 0 && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          {/* The allowlist verbatim. It is what an agent may call and nothing
              more, so listing it is listing the blast radius of a stray plan. */}
          Tools: {agent.tools.join(", ")}
        </p>
      )}
    </li>
  );
}
