/**
 * The A2UI renderer.
 *
 * Two properties hold this together, and they live in different places:
 *
 *   1. **Runtime**: anything outside the allowlist is REJECTED here, never
 *      rendered and never silently skipped.
 *   2. **Compile time**: `allowlist.ts` asserts that the allowlist and the
 *      generated union are the same set, in both directions.
 *
 * Note that the `never` in the default branch below is *not* what catches a
 * component added server-side. It narrows over `AllowedComponent`, so it only
 * proves this switch covers the allowlist. The generated-union check is the one
 * that fails when the contract grows - see allowlist.ts, which explains why one
 * check alone is insufficient.
 *
 * Together: a component cannot be added server-side and quietly go unrendered,
 * nor rendered client-side without existing server-side.
 *
 * What is deliberately absent: no `dangerouslySetInnerHTML`, no agent-supplied
 * URLs, no agent-supplied styling. `Image` takes an ArtifactRef which the server
 * resolves - see docs/adr/0006-agentic-ui-protocols.md.
 *
 * Phase: 4 - Delivery Flow
 */
import type { JSX } from "react";
import type { A2UIComponent, A2UISurface } from "@/types/generated/contracts";
import { isAllowedComponent, UnsupportedComponentError } from "./allowlist";

interface RenderProps {
  surface: A2UISurface;
  /** Resolved artifact URLs, keyed by ArtifactRef.key. Server-resolved only. */
  artifacts?: Record<string, string>;
}

function childrenOf(surface: A2UISurface, component: A2UIComponent): A2UIComponent[] {
  const byId = new Map((surface.components ?? []).map((c) => [c.id, c]));
  return (component.children ?? [])
    .map((id) => byId.get(id))
    .filter((c): c is A2UIComponent => c !== undefined);
}

/**
 * Render one component. Throws UnsupportedComponentError for anything the
 * allowlist does not cover.
 */
export function renderComponent(
  component: A2UIComponent,
  surface: A2UISurface,
  artifacts: Record<string, string>,
): JSX.Element {
  if (!isAllowedComponent(component.component)) {
    throw new UnsupportedComponentError(component.component);
  }

  const kids = childrenOf(surface, component).map((child) => (
    <div key={child.id}>{renderComponent(child, surface, artifacts)}</div>
  ));

  switch (component.component) {
    case "Row":
      return <div className="flex flex-row gap-3">{kids}</div>;
    case "Column":
      return <div className="flex flex-col gap-3">{kids}</div>;
    case "Card":
      return (
        <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">{kids}</div>
      );
    case "List":
      return <ul className="list-disc pl-5">{kids}</ul>;
    case "Text":
      return <p>{component.text ?? ""}</p>;
    case "Image": {
      // Never an agent-supplied URL. The key is resolved server-side, and an
      // unresolved reference renders as its alt text rather than a broken link.
      const key = component.artifact_ref?.key;
      const src = key ? artifacts[key] : undefined;
      const alt = component.artifact_ref?.alt_text ?? "";
      return src ? (
        // biome-ignore lint/performance/noImgElement: A2UI artifacts are server-resolved signed URLs, not statically known assets, so next/image cannot optimise them.
        <img src={src} alt={alt} className="max-w-full rounded" />
      ) : (
        <span className="text-slate-500">{alt}</span>
      );
    }
    case "Icon":
      return <span aria-hidden="true">{component.text ?? "•"}</span>;
    case "Divider":
      return <hr className="border-slate-200 dark:border-slate-800" />;
    case "TextField":
      return (
        <label className="flex flex-col gap-1">
          <span className="text-sm">{component.label ?? ""}</span>
          <input className="rounded border border-slate-300 px-2 py-1" type="text" />
        </label>
      );
    case "CheckBox":
      return (
        <label className="flex items-center gap-2">
          <input type="checkbox" />
          <span>{component.label ?? ""}</span>
        </label>
      );
    case "ChoicePicker":
      return (
        <label className="flex flex-col gap-1">
          <span className="text-sm">{component.label ?? ""}</span>
          <select className="rounded border border-slate-300 px-2 py-1">{kids}</select>
        </label>
      );
    case "DateTimeInput":
      return (
        <label className="flex flex-col gap-1">
          <span className="text-sm">{component.label ?? ""}</span>
          <input className="rounded border border-slate-300 px-2 py-1" type="datetime-local" />
        </label>
      );
    case "Button":
      return (
        <button className="rounded bg-slate-900 px-3 py-1.5 text-white" type="button">
          {component.text ?? component.label ?? "Submit"}
        </button>
      );
    default: {
      // Exhaustiveness check. If the generated union grows and this switch does
      // not, `never` stops type-checking and the build fails.
      const unhandled: never = component.component;
      throw new UnsupportedComponentError(String(unhandled));
    }
  }
}

/** Render a whole surface from its root component. */
export function A2UISurfaceView({ surface, artifacts = {} }: RenderProps): JSX.Element {
  const root = (surface.components ?? []).find((c) => c.id === surface.root);
  if (!root) {
    throw new Error(`A2UI surface ${surface.id} has no component matching root "${surface.root}"`);
  }
  return <div data-surface-kind={surface.kind}>{renderComponent(root, surface, artifacts)}</div>;
}
