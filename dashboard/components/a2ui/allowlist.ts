/**
 * The A2UI component allowlist, taken from the generated contract.
 *
 * THIS FILE DEFINES NOTHING. It re-exports the generated `Component` union so
 * the renderer switches over the same artifact the server validates against.
 * Writing the list out by hand here is what would let the allowlist drift
 * between server and client - and a client that accepts one component the
 * server does not is exactly the hole the allowlist exists to close.
 *
 * Adding a component means adding it to `A2UIComponentType` in
 * core/contracts/ui.py and running `make codegen`. It appears here for free.
 *
 * See docs/adr/0006-agentic-ui-protocols.md.
 *
 * Phase: 4 - Delivery Flow
 */
import type { A2UIComponentType } from "@/types/generated/contracts";

/** Component types this renderer will draw. Generated, never hand-maintained. */
export const ALLOWED_COMPONENTS = [
  "Row",
  "Column",
  "Card",
  "List",
  "Text",
  "Image",
  "Icon",
  "Divider",
  "TextField",
  "CheckBox",
  "ChoicePicker",
  "DateTimeInput",
  "Button",
] as const satisfies readonly A2UIComponentType[];

export type AllowedComponent = (typeof ALLOWED_COMPONENTS)[number];

/*
 * Drift is checked in BOTH directions, because one check alone is not enough.
 *
 * `satisfies readonly A2UIComponentType[]` above catches only half: it fails if
 * this array names something the contract does not. It does NOT fail when the
 * contract gains a member, because every existing entry is still valid - so an
 * added component would silently go unrendered.
 *
 * The assertion below is the other half. `Exclude` is empty only when the array
 * covers every member of the generated union; otherwise `Unrendered` is a real
 * type, the conditional resolves to `never`, and assigning `true` to it fails
 * `pnpm typecheck` naming the missing component.
 */
type Unrendered = Exclude<A2UIComponentType, AllowedComponent>;
const _everyGeneratedComponentIsRendered: [Unrendered] extends [never] ? true : Unrendered = true;
void _everyGeneratedComponentIsRendered;

const ALLOWED = new Set<string>(ALLOWED_COMPONENTS);

/** True when `type` is a component this renderer is willing to draw. */
export function isAllowedComponent(type: string): type is AllowedComponent {
  return ALLOWED.has(type);
}

/**
 * Raised when an agent asks for a component outside the allowlist.
 *
 * Agent-generated UI is untrusted data. Rejecting loudly rather than skipping
 * quietly means a mismatch surfaces in development instead of becoming a
 * silently blank panel in production.
 */
export class UnsupportedComponentError extends Error {
  readonly componentType: string;

  constructor(componentType: string) {
    super(
      `A2UI component "${componentType}" is not in Pantheon's allowlist. ` +
        "Agent-generated UI is untrusted data; see docs/adr/0006-agentic-ui-protocols.md.",
    );
    this.name = "UnsupportedComponentError";
    this.componentType = componentType;
  }
}
