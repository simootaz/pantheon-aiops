/**
 * Where the dashboard's token comes from, and what is honestly missing.
 *
 * THERE IS NO SIGN-IN FLOW YET
 * ----------------------------
 * `api/auth/dependencies.py` authenticates opaque bearer tokens configured
 * against a subject and roles. There is no login endpoint, no session cookie
 * and no identity provider - that is Phase 7 work, in front of a real IdP, and
 * inventing a half of it here would produce a login screen that authenticates
 * against nothing.
 *
 * So the token is read from `sessionStorage` under a documented key, and a view
 * with no token says so. It does NOT show an empty list: "you are not signed in"
 * and "there are no investigations" are different facts, and a dashboard that
 * renders the second for the first sends somebody looking for a missing run.
 *
 * `sessionStorage` rather than `localStorage`: it dies with the tab, so a
 * shared machine does not carry a token into the next person's session.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { useEffect, useState } from "react";

/** Where the token lives. One name, so nothing else invents a second. */
export const TOKEN_KEY = "pantheon.token";

/**
 * The current token, or `null`.
 *
 * Read through a hook rather than at module scope: `sessionStorage` does not
 * exist during server rendering, and reading it there throws in a way Next
 * reports as a render error rather than as a missing browser API.
 */
export function useToken(): { token: string | null; ready: boolean } {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      setToken(window.sessionStorage.getItem(TOKEN_KEY));
    } catch {
      // Storage can be unavailable - a private window, or a browser configured
      // to block it. Treated as "no token" rather than as a crash: the view
      // then says what to do, which is more useful than a blank page.
      setToken(null);
    }
    // `ready` distinguishes "we have not looked yet" from "we looked and there
    // is nothing". Without it every page flashes its signed-out state on first
    // paint, which reads as being logged out.
    setReady(true);
  }, []);

  return { token, ready };
}

/** Store a token for this tab. Used by whatever sign-in eventually exists. */
export function setToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

/** Forget it. */
export function clearToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}
