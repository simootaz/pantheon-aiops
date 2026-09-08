/**
 * Provider settings: the card, the tier pickers, and the probe button.
 *
 * WHY THE MODEL LIST SAYS WHERE IT CAME FROM
 * ------------------------------------------
 * `GET /providers/{id}/models` asks the provider, and falls back to the
 * configured `manual_models` when it cannot be reached. Those two lists look
 * identical on screen and mean opposite things: one was verified a second ago,
 * the other was typed by hand and may name a model the vendor deprecated last
 * quarter. Binding a tier against the second is the failure ADR 0004 puts at
 * 03:00 instead of at settings time - so `live` is rendered, not swallowed.
 *
 * WHY THE PROBE IS A BUTTON AND NOT AN EFFECT
 * -------------------------------------------
 * Every probe is a real request charged to whoever pressed it. The endpoint
 * says it runs on demand and never on a timer; a card that probed when it
 * opened would turn browsing the settings page into a bill, and the person
 * paying would have no idea what they did.
 *
 * WHY THERE IS NO KEY FIELD SHOWING THE KEY
 * -----------------------------------------
 * The API refuses to return one even masked. `has_key` says whether there is
 * one; changing it means sending a new one. A box pre-filled with dots that
 * silently means "unchanged" is how a key gets cleared by someone tidying up.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { type JSX, useState } from "react";
import type { Provider, ProviderModels } from "@/lib/api";

/** The three bands an agent asks for. A model is never named by an agent. */
export const TIERS = ["cheap", "balanced", "frontier"] as const;
export type TierName = (typeof TIERS)[number];

/**
 * Whether this provider can serve a request right now, as far as configuration
 * can tell.
 *
 * Configuration only. A provider can be enabled, keyed, bound, and still
 * unreachable - which is what the probe is for, and why this says "configured"
 * rather than "working".
 */
export function configurationGaps(provider: Provider): string[] {
  const gaps: string[] = [];
  if (!provider.enabled) gaps.push("disabled");
  // `auth_mode: none` is a local provider that wants no credential - Ollama,
  // LM Studio, vLLM. Demanding a key there would report a fault that is a
  // deliberate configuration.
  if (provider.auth_mode !== "none" && !provider.has_key) gaps.push("no key");
  if (Object.keys(provider.tiers).length === 0) gaps.push("no tier bound");
  return gaps;
}

export interface ProviderCardProps {
  provider: Provider;
  /** What the provider serves, once someone asked. Null until then. */
  models: ProviderModels | null;
  busy?: boolean;
  error?: string | null;
  onLoadModels: () => void;
  onBindTiers: (tiers: Record<TierName, string | null>) => void;
  onProbe: (models: string[]) => void;
}

export function ProviderCard({
  provider,
  models,
  busy = false,
  error = null,
  onLoadModels,
  onBindTiers,
  onProbe,
}: ProviderCardProps): JSX.Element {
  const [draft, setDraft] = useState<Record<string, string>>(provider.tiers);
  const gaps = configurationGaps(provider);

  return (
    <li className="rounded border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-medium">{provider.display_name}</h2>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {provider.dialect} · {provider.base_url}
        </span>
      </div>

      {gaps.length > 0 && (
        <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
          Not usable yet: {gaps.join(", ")}
        </p>
      )}

      {error && <p className="mt-2 text-sm text-red-700 dark:text-red-400">{error}</p>}

      {models === null ? (
        <button
          type="button"
          className="mt-3 rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700"
          disabled={busy}
          onClick={onLoadModels}
        >
          Ask what it serves
        </button>
      ) : (
        <div className="mt-3">
          {/* The provenance of the list, said before the picker that uses it.
              A reader who has already chosen a model does not go back and
              re-read a note under the dropdown. */}
          {models.live ? (
            <p className="text-xs text-emerald-700 dark:text-emerald-400">
              {models.models.length} models, live from the provider
            </p>
          ) : (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              The provider could not be reached. These {models.models.length} are the configured
              manual list, not what it serves today.
            </p>
          )}

          {/* The check that is cheap now and an outage later. Rendered above
              the pickers for the same reason as the provenance line. */}
          {models.warnings.map((warning) => (
            <p key={warning} className="mt-1 text-xs text-red-700 dark:text-red-400">
              {warning}
            </p>
          ))}

          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {TIERS.map((tier) => (
              <label key={tier} className="text-xs text-slate-500 dark:text-slate-400">
                {tier}
                <select
                  aria-label={tier}
                  className="mt-1 w-full rounded border border-slate-300 p-1 text-sm dark:border-slate-700 dark:bg-slate-900"
                  value={draft[tier] ?? ""}
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, [tier]: event.target.value }))
                  }
                >
                  <option value="">— unbound —</option>
                  {models.models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>

          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="rounded bg-slate-800 px-3 py-1 text-sm text-white disabled:opacity-50 dark:bg-slate-200 dark:text-slate-900"
              disabled={busy}
              onClick={() =>
                onBindTiers({
                  cheap: draft.cheap || null,
                  balanced: draft.balanced || null,
                  frontier: draft.frontier || null,
                })
              }
            >
              Bind tiers
            </button>
            <button
              type="button"
              className="rounded border border-slate-300 px-3 py-1 text-sm disabled:opacity-50 dark:border-slate-700"
              // Disabled with nothing bound rather than probing everything: a
              // provider can list dozens of models and each probe is paid.
              disabled={busy || Object.values(draft).filter(Boolean).length === 0}
              onClick={() => onProbe([...new Set(Object.values(draft).filter(Boolean))])}
            >
              Probe bound models
            </button>
          </div>

          {/* Said on the button's own terms, next to it. A cost mentioned in a
              tooltip is a cost nobody read. */}
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Probing sends a real request to each model and is charged to this provider&rsquo;s
            account. Nothing here probes on its own.
          </p>
        </div>
      )}
    </li>
  );
}
