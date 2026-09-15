/**
 * Settings.
 *
 * Delphi providers: which are configured, what they serve, and which model
 * backs each tier. Agents ask for a tier and never for a model, so this page is
 * the only place a model id is chosen by a person.
 *
 * WHAT IS NOT HERE, AND WHY
 * -------------------------
 * **Per-agent model overrides.** `core/llm/resolver.py` reads them from
 * `ResolutionPolicy.per_agent`, and nothing persists or serves one - there is
 * no store and no endpoint. A picker here would write to nowhere and read back
 * its own optimism.
 *
 * **Cerberus grants and the credential inventory.** Same reason: the grant book
 * is in-process and has no API. Both are recorded as gaps in the repository map
 * rather than mocked up here, because a settings control that changes nothing
 * is worse than an absent one - somebody sets it and believes it took.
 *
 * Phase: 4 - Delivery Flow
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { ProviderCard, type TierName } from "@/components/providers";
import { Empty, Loading, Refused, SignedOut } from "@/components/states";
import {
  ApiError,
  bindTiers,
  type Provider,
  type ProviderModels,
  probeProvider,
  providerModels,
  providers,
} from "@/lib/api";
import { useToken } from "@/lib/session";

export default function SettingsPage() {
  const { token, ready } = useToken();
  const [configured, setConfigured] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, ProviderModels>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [probes, setProbes] = useState<Record<string, string>>({});

  const load = useCallback(async (): Promise<void> => {
    try {
      setConfigured(await providers(token));
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [token]);

  useEffect(() => {
    if (!ready || !token) return;
    void load();
  }, [ready, token, load]);

  /** Run one provider action, recording its refusal on that provider's card. */
  async function act(id: string, work: () => Promise<void>): Promise<void> {
    setBusy(id);
    setFailures((previous) => ({ ...previous, [id]: "" }));
    try {
      await work();
    } catch (caught: unknown) {
      // A 502 here means the provider could not be asked - which is a fact
      // about the provider, not about this page, and belongs on its card.
      setFailures((previous) => ({
        ...previous,
        [id]: caught instanceof ApiError ? caught.message : String(caught),
      }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Agents ask for a tier, never for a model. This is the only place a model is chosen.
      </p>

      <div className="mt-4">
        {!ready ? (
          <Loading what="session" />
        ) : !token ? (
          <SignedOut />
        ) : error ? (
          <Refused message={error} />
        ) : configured === null ? (
          <Loading what="providers" />
        ) : configured.length === 0 ? (
          <Empty what="providers configured" />
        ) : (
          <ul className="grid gap-3">
            {configured.map((provider) => (
              <div key={provider.id}>
                <ProviderCard
                  provider={provider}
                  models={models[provider.id] ?? null}
                  busy={busy === provider.id}
                  error={failures[provider.id] || null}
                  onLoadModels={() => {
                    void act(provider.id, async () => {
                      const found = await providerModels(provider.id, token);
                      setModels((previous) => ({ ...previous, [provider.id]: found }));
                    });
                  }}
                  onBindTiers={(tiers: Record<TierName, string | null>) => {
                    void act(provider.id, async () => {
                      await bindTiers(provider.id, tiers, token);
                      // Refetched rather than patched locally: the endpoint
                      // validates bindings against what the provider serves and
                      // can refuse one, so the stored tiers are the answer.
                      await load();
                    });
                  }}
                  onProbe={(chosen: string[]) => {
                    void act(provider.id, async () => {
                      const result = await probeProvider(provider.id, chosen, token);
                      setProbes((previous) => ({
                        ...previous,
                        [provider.id]:
                          `reachable: ${result.reachable.join(", ") || "none"}` +
                          (result.unreachable.length > 0
                            ? ` · unreachable: ${result.unreachable.join(", ")}`
                            : ""),
                      }));
                    });
                  }}
                />
                {probes[provider.id] && (
                  <p className="mt-1 px-4 text-xs text-slate-600 dark:text-slate-400">
                    {probes[provider.id]}
                  </p>
                )}
              </div>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
