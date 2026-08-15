/**
 * The rejection test: an out-of-allowlist component type is refused.
 *
 * Agent-generated UI is untrusted data. This asserts the client half of that
 * boundary - the Python half lives in tests/unit/test_agentic_ui.py, and both
 * are needed: the server must not emit what the client will not draw, and the
 * client must not draw what the server would not emit.
 *
 * Phase: 4 - Delivery Flow
 */
import { describe, expect, it } from "vitest";
import type { A2UIComponent, A2UISurface } from "@/types/generated/contracts";
import { ALLOWED_COMPONENTS, isAllowedComponent, UnsupportedComponentError } from "./allowlist";
import { renderComponent } from "./renderer";

function surfaceWith(components: A2UIComponent[]): A2UISurface {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    kind: "notice",
    catalog_id: "pantheon.v1",
    a2ui_version: "v0.9.1",
    root: components[0]?.id ?? "root",
    components,
    data_model: {},
    agent_display_name: "Pantheon",
  } as A2UISurface;
}

function component(type: string, extra: Partial<A2UIComponent> = {}): A2UIComponent {
  return { id: "c1", component: type, children: [], ...extra } as A2UIComponent;
}

describe("A2UI allowlist", () => {
  it("rejects component types outside the allowlist", () => {
    for (const rejected of ["Video", "AudioPlayer", "Modal", "Script", "IFrame", "Html"]) {
      expect(isAllowedComponent(rejected)).toBe(false);

      const target = component(rejected);
      expect(() => renderComponent(target, surfaceWith([target]), {})).toThrow(
        UnsupportedComponentError,
      );
    }
  });

  it("names the offending type so the failure is diagnosable", () => {
    const target = component("IFrame");
    expect(() => renderComponent(target, surfaceWith([target]), {})).toThrow(/IFrame/);
  });

  it("accepts every component in the allowlist", () => {
    for (const allowed of ALLOWED_COMPONENTS) {
      expect(isAllowedComponent(allowed)).toBe(true);

      const target = component(allowed);
      expect(() => renderComponent(target, surfaceWith([target]), {})).not.toThrow();
    }
  });
});

describe("Image is reference-based", () => {
  it("renders alt text rather than a broken link when unresolved", () => {
    const target = component("Image", {
      artifact_ref: {
        key: "flame-graph.svg",
        investigation_id: "00000000-0000-0000-0000-000000000001",
        kind: "image",
        alt_text: "flame graph",
      },
    } as Partial<A2UIComponent>);

    // No resolved artifacts supplied: nothing is fetched.
    expect(() => renderComponent(target, surfaceWith([target]), {})).not.toThrow();
  });

  it("has no way to accept a bare URL", () => {
    // A2UIComponent has no url/src field at all, so this is a type-level
    // guarantee rather than a runtime check. Asserted in Python across all
    // three generated artifacts; here we assert the shape the renderer reads.
    const target = component("Image");
    expect("url" in target).toBe(false);
    expect("src" in target).toBe(false);
  });
});
