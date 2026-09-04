/**
 * The pieces the investigation views are made of.
 *
 * They live here rather than in the pages because Next's route types forbid a
 * page module from exporting anything but the route's own contract - a page
 * that exported a component would fail `tsc`. Which is convenient: it means
 * these are importable by a test that renders one row without standing up a
 * route, a session and a stream to see it.
 *
 * Phase: 4 - Delivery Flow
 */
import Link from "next/link";
import type { JSX } from "react";
import { degraded, headline, isPartial, isTerminal } from "@/lib/investigations";
import type { Investigation } from "@/types/generated/contracts";

/** How a run reads at a glance: what it was about, and whether it is whole. */
export function Row({ investigation }: { investigation: Investigation }): JSX.Element {
  return (
    <li className="border-b border-slate-200 py-3 last:border-0 dark:border-slate-800">
      <Link className="font-medium hover:underline" href={`/investigations/${investigation.id}`}>
        {headline(investigation)}
      </Link>
      <div className="mt-1 flex gap-3 text-xs text-slate-500 dark:text-slate-400">
        <span>{investigation.state}</span>
        <span>{investigation.findings?.length ?? 0} findings</span>
        {/* Shown because it is the difference between "nobody found anything"
            and "nobody looked" - the distinction the DEGRADED kind exists to
            preserve, and the one a findings count on its own destroys. */}
        {isPartial(investigation) && (
          <span className="text-amber-600 dark:text-amber-400">partial</span>
        )}
        <span>{investigation.created_at}</span>
      </div>
    </li>
  );
}

/**
 * Whether the stream is open, and whether that is expected.
 *
 * A finished run has nothing left to send, so a closed stream is correct and
 * says "finished". A running one with a closed stream is reconnecting. Reading
 * both the connection and the run state is the only way to tell those apart -
 * on `connected` alone, every completed investigation would sit there claiming
 * to be reconnecting forever.
 */
export function Status({
  investigation,
  connected,
  fatal,
}: {
  investigation: Investigation;
  connected: boolean;
  fatal: boolean;
}): JSX.Element {
  if (fatal) return <span className="text-xs text-red-700 dark:text-red-400">stopped</span>;
  if (isTerminal(investigation)) {
    return <span className="text-xs text-slate-500 dark:text-slate-400">finished</span>;
  }
  return connected ? (
    <span className="text-xs text-emerald-700 dark:text-emerald-400">live</span>
  ) : (
    <span className="text-xs text-amber-600 dark:text-amber-400">reconnecting</span>
  );
}

/**
 * What did not happen, said plainly and above the verdict.
 *
 * Placed before the conclusion on purpose. A reader who has already accepted
 * "memory leak, confidence 0.72" does not go back and re-weigh it after
 * scrolling past a note that the log search never ran.
 */
export function Gaps({ investigation }: { investigation: Investigation }): JSX.Element | null {
  const gaps = degraded(investigation);
  if (gaps.length === 0) return null;

  return (
    <div className="mt-4 rounded border border-amber-300 p-4 text-sm dark:border-amber-800">
      <p className="font-medium text-amber-700 dark:text-amber-400">
        Partial: {gaps.length} step{gaps.length === 1 ? "" : "s"} could not run
      </p>
      <ul className="mt-2">
        {gaps.map((gap) => (
          <li key={gap.id} className="text-slate-600 dark:text-slate-400">
            {gap.agent}: {gap.title}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One finding, one line. */
export function FindingRow({
  finding,
}: {
  finding: NonNullable<Investigation["findings"]>[number];
}): JSX.Element {
  return (
    <li className="border-b border-slate-200 py-2 text-sm last:border-0 dark:border-slate-800">
      <span className="font-medium">{finding.title}</span>
      <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
        {finding.agent} · {finding.severity}
      </span>
    </li>
  );
}
