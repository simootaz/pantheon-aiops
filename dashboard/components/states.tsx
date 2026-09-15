/**
 * The four states every view has, kept apart on purpose.
 *
 * Loading, signed out, refused, and empty are different facts and a dashboard
 * that renders one for another sends somebody to look in the wrong place:
 *
 *   - "there are no investigations" shown to somebody whose token expired sends
 *     them hunting for a run that is sitting right there;
 *   - a spinner shown for a rejected credential waits forever;
 *   - "nothing found" shown while the first request is still open reads as an
 *     answer rather than as a question still being asked.
 *
 * They are components rather than a convention so a new view gets all four by
 * using them, instead of by remembering that four exist.
 *
 * Phase: 4 - Delivery Flow
 */
import type { JSX, ReactNode } from "react";

function Panel({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="rounded border border-slate-200 p-6 text-sm dark:border-slate-800">
      {children}
    </div>
  );
}

/** A request is still open. Not an answer. */
export function Loading({ what }: { what: string }): JSX.Element {
  return (
    <Panel>
      <span className="text-slate-500 dark:text-slate-400">Loading {what}…</span>
    </Panel>
  );
}

/**
 * No token in this tab.
 *
 * Says what to do rather than just what is wrong. There is no sign-in flow yet
 * - see `lib/session.ts` - so the instruction is the honest one.
 */
export function SignedOut(): JSX.Element {
  return (
    <Panel>
      <p className="font-medium">Not signed in</p>
      <p className="mt-1 text-slate-600 dark:text-slate-400">
        This tab has no API token. Pantheon has no sign-in flow yet; set one in
        <code className="mx-1 rounded bg-slate-100 px-1 dark:bg-slate-800">
          sessionStorage.pantheon.token
        </code>
        to read your tenant&rsquo;s investigations.
      </p>
    </Panel>
  );
}

/** The API refused. The status is shown because 401 and 503 are different days. */
export function Refused({ message }: { message: string }): JSX.Element {
  return (
    <Panel>
      <p className="font-medium text-red-700 dark:text-red-400">Could not load</p>
      <p className="mt-1 text-slate-600 dark:text-slate-400">{message}</p>
    </Panel>
  );
}

/**
 * The request succeeded and there is nothing.
 *
 * A real answer, and phrased as one. "No investigations yet" is a fact about a
 * quiet system, which is different from every failure above it.
 */
export function Empty({ what }: { what: string }): JSX.Element {
  return (
    <Panel>
      <span className="text-slate-500 dark:text-slate-400">No {what} yet.</span>
    </Panel>
  );
}
