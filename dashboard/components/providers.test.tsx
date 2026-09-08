/**
 * The three things the provider card must not let a reader assume.
 *
 * That a fallback model list came from the provider. That a probe is free. That
 * a provider with no key is broken when it wanted none. Each is a sentence
 * someone acts on, so each is asserted against the rendered card.
 *
 * Phase: 4 - Delivery Flow
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Provider, ProviderModels } from "@/lib/api";
import { configurationGaps, ProviderCard } from "./providers";

function provider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: "44444444-4444-4444-4444-444444444444",
    provider_id: "groq",
    display_name: "Groq",
    dialect: "chat_completions",
    base_url: "https://api.groq.com/openai/v1",
    auth_mode: "bearer",
    enabled: true,
    manual_models: [],
    has_key: true,
    tiers: { cheap: "llama-3.1-8b-instant" },
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function served(overrides: Partial<ProviderModels> = {}): ProviderModels {
  return {
    provider_id: "groq",
    live: true,
    models: ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"],
    tiers: { cheap: "llama-3.1-8b-instant" },
    stale_tier_bindings: {},
    warnings: [],
    ...overrides,
  };
}

function card(props: Partial<Parameters<typeof ProviderCard>[0]> = {}) {
  return (
    <ul>
      <ProviderCard
        provider={provider()}
        models={null}
        onLoadModels={vi.fn()}
        onBindTiers={vi.fn()}
        onProbe={vi.fn()}
        {...props}
      />
    </ul>
  );
}

describe("configurationGaps", () => {
  it("does not call a keyless local provider broken", () => {
    // `auth_mode: none` is Ollama, LM Studio, vLLM - a provider that wants no
    // credential. Reporting "no key" there is reporting a fault that is a
    // deliberate configuration, and it teaches people to ignore the warning.
    expect(configurationGaps(provider({ auth_mode: "none", has_key: false }))).toEqual([]);
  });

  it("does say so when a provider that needs a key has none", () => {
    // The control on the previous test. A check that never complained would
    // pass it and never report the case it exists for.
    expect(configurationGaps(provider({ auth_mode: "bearer", has_key: false }))).toContain(
      "no key",
    );
  });

  it("reports a provider with no tier bound", () => {
    // Enabled, keyed, reachable, and no agent can use it: a tier is what an
    // agent asks for, and an unbound one resolves to nothing.
    expect(configurationGaps(provider({ tiers: {} }))).toContain("no tier bound");
  });

  it("reports nothing for a fully configured provider", () => {
    expect(configurationGaps(provider())).toEqual([]);
  });
});

describe("where the model list came from", () => {
  it("says a fallback list is not what the provider serves today", () => {
    // The failure ADR 0004 puts at 03:00 rather than at settings time. A
    // fallback list and a live one look identical and mean opposite things.
    render(card({ models: served({ live: false }) }));

    expect(screen.getByText(/could not be reached/)).toBeDefined();
    expect(screen.getByText(/manual list, not what it serves today/)).toBeDefined();
  });

  it("says a live list is live", () => {
    // The control. A card that always warned would make the warning noise.
    render(card({ models: served({ live: true }) }));

    expect(screen.queryByText(/could not be reached/)).toBeNull();
    expect(screen.getByText(/live from the provider/)).toBeDefined();
  });

  it("shows a stale binding as a warning, not as a silent absence", () => {
    render(
      card({
        models: served({
          warnings: [
            "the cheap tier is bound to 'mixtral-8x7b', which this provider no longer serves",
          ],
        }),
      }),
    );

    expect(screen.getByText(/no longer serves/)).toBeDefined();
  });
});

describe("probing", () => {
  it("says the probe costs money, next to the button", () => {
    // A cost mentioned in a tooltip is a cost nobody read.
    render(card({ models: served() }));

    expect(screen.getByText(/charged to this provider/)).toBeDefined();
  });

  it("does not probe when the card opens", () => {
    // The endpoint runs on demand and never on a timer. A card that probed on
    // render would turn browsing settings into a bill.
    const onProbe = vi.fn();
    render(card({ models: served(), onProbe }));

    expect(onProbe).not.toHaveBeenCalled();
  });

  it("probes only the bound models, and only when asked", () => {
    // Not everything the provider lists: that can be dozens of paid requests.
    const onProbe = vi.fn();
    render(card({ models: served(), onProbe }));

    fireEvent.click(screen.getByRole("button", { name: "Probe bound models" }));

    expect(onProbe).toHaveBeenCalledWith(["llama-3.1-8b-instant"]);
  });

  it("refuses to probe with nothing bound", () => {
    const onProbe = vi.fn();
    render(card({ provider: provider({ tiers: {} }), models: served(), onProbe }));
    const button = screen.getByRole("button", { name: "Probe bound models" });

    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.click(button);
    expect(onProbe).not.toHaveBeenCalled();
  });
});

describe("binding tiers", () => {
  it("sends an unbound tier as null rather than as an empty string", () => {
    // `TierBinding` drops falsy values, so "" and null both unbind - but "" is
    // also a model id the API would have to reject. Null says what is meant.
    const onBindTiers = vi.fn();
    render(card({ models: served(), onBindTiers }));

    fireEvent.click(screen.getByRole("button", { name: "Bind tiers" }));

    expect(onBindTiers).toHaveBeenCalledWith({
      cheap: "llama-3.1-8b-instant",
      balanced: null,
      frontier: null,
    });
  });

  it("sends what was picked", () => {
    const onBindTiers = vi.fn();
    render(card({ models: served(), onBindTiers }));

    fireEvent.change(screen.getByLabelText("frontier"), {
      target: { value: "llama-3.3-70b-versatile" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind tiers" }));

    expect(onBindTiers).toHaveBeenCalledWith({
      cheap: "llama-3.1-8b-instant",
      balanced: null,
      frontier: "llama-3.3-70b-versatile",
    });
  });
});

describe("the key", () => {
  it("is nowhere on the card", () => {
    // The API refuses to return one even masked, and a box pre-filled with dots
    // meaning "unchanged" is how a key gets cleared by someone tidying up.
    const { container } = render(card({ models: served() }));

    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(screen.queryByText(/api.?key/i)).toBeNull();
  });
});
