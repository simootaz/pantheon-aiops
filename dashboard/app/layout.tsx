import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

/**
 * Root layout.
 *
 * Phase: 4 - Delivery Flow
 */
export const metadata: Metadata = {
  title: "Pantheon",
  description: "Polyglot multi-agent AIOps platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <nav className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <ul className="flex gap-6 text-sm">
            <li>
              <a href="/investigations">Investigations</a>
            </li>
            <li>
              <a href="/agents">Agents</a>
            </li>
            <li>
              <a href="/approvals">Approvals</a>
            </li>
            <li>
              <a href="/settings">Settings</a>
            </li>
          </ul>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
