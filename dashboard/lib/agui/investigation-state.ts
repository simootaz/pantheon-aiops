/**
 * The shared state object is the Investigation.
 *
 * AG-UI carries exactly one state object for a Pantheon run: `StateSnapshot` at
 * `RunStarted`, then `StateDelta` (RFC 6902 JSON Patch) for every change. This
 * module applies that sequence and nothing else.
 *
 * Snapshot plus ordered patches reconstructs any run exactly, which is what
 * makes replay a property of the design rather than a feature to build - an
 * operator can scrub back through an incident and see what the platform knew at
 * each moment.
 *
 * See docs/adr/0006-agentic-ui-protocols.md.
 *
 * Phase: 4 - Delivery Flow
 */
import type { Investigation } from "@/types/generated/contracts";

/** One RFC 6902 operation. Shaped by the spec, not by us. */
export interface JsonPatchOperation {
  op: "add" | "remove" | "replace" | "move" | "copy" | "test";
  path: string;
  value?: unknown;
  from?: string;
}

/** Decode an RFC 6901 pointer token: `~1` is `/`, `~0` is `~`. */
function decodeToken(token: string): string {
  return token.replace(/~1/g, "/").replace(/~0/g, "~");
}

function parsePointer(pointer: string): string[] {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) {
    throw new Error(`invalid JSON Pointer: ${pointer}`);
  }
  return pointer.slice(1).split("/").map(decodeToken);
}

type Mutable = Record<string, unknown> | unknown[];

function isContainer(value: unknown): value is Mutable {
  return typeof value === "object" && value !== null;
}

function setAt(container: Mutable, key: string, value: unknown, insert: boolean): void {
  if (Array.isArray(container)) {
    const index = key === "-" ? container.length : Number(key);
    if (Number.isNaN(index)) throw new Error(`invalid array index: ${key}`);
    if (insert) container.splice(index, 0, value);
    else container[index] = value;
    return;
  }
  (container as Record<string, unknown>)[key] = value;
}

function removeAt(container: Mutable, key: string): void {
  if (Array.isArray(container)) {
    const index = Number(key);
    if (Number.isNaN(index)) throw new Error(`invalid array index: ${key}`);
    container.splice(index, 1);
    return;
  }
  delete (container as Record<string, unknown>)[key];
}

function resolveParent(root: Mutable, tokens: string[]): Mutable {
  let current: unknown = root;
  for (const token of tokens) {
    if (!isContainer(current)) {
      throw new Error(`JSON Pointer does not resolve: /${tokens.join("/")}`);
    }
    current = Array.isArray(current)
      ? current[Number(token)]
      : (current as Record<string, unknown>)[token];
  }
  if (!isContainer(current)) {
    throw new Error(`JSON Pointer does not resolve to a container: /${tokens.join("/")}`);
  }
  return current;
}

/**
 * Apply one patch operation, returning a new object.
 *
 * Copied rather than mutated so React sees a changed reference and re-renders.
 */
export function applyPatch<T>(state: T, operations: readonly JsonPatchOperation[]): T {
  const next = structuredClone(state) as unknown as Mutable;

  for (const operation of operations) {
    const tokens = parsePointer(operation.path);
    const key = tokens.pop();
    if (key === undefined) {
      throw new Error(`operation ${operation.op} cannot target the document root`);
    }
    const parent = resolveParent(next, tokens);

    switch (operation.op) {
      case "add":
        setAt(parent, key, operation.value, Array.isArray(parent));
        break;
      case "replace":
        setAt(parent, key, operation.value, false);
        break;
      case "remove":
        removeAt(parent, key);
        break;
      default:
        // move, copy and test are unused by the backend today. Throwing keeps
        // an unhandled op visible rather than silently desynchronising state.
        throw new Error(`unsupported JSON Patch op: ${operation.op}`);
    }
  }

  return next as unknown as T;
}

/** Tracks the Investigation across one AG-UI run. */
export class InvestigationStore {
  private state: Investigation | null = null;

  /** StateSnapshot: replaces everything. */
  snapshot(investigation: Investigation): void {
    this.state = investigation;
  }

  /** StateDelta: applies patches in order. */
  delta(operations: readonly JsonPatchOperation[]): void {
    if (this.state === null) {
      throw new Error("received StateDelta before StateSnapshot");
    }
    this.state = applyPatch(this.state, operations);
  }

  current(): Investigation | null {
    return this.state;
  }
}

// TODO: Phase 4 - expose this as a React hook over the AG-UI event stream
