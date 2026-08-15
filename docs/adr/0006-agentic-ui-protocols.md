# ADR 0006 — Agentic UI: AG-UI transport, A2UI payload

- **Status:** Accepted
- **Date:** 2026-08-15
- **Decided on branch:** `feature/agentic-ui-protocols`
- **Implementation:** Phase 4. Supersedes the bespoke WebSocket layer in `api/ws/`.

## Context

`api/ws/stream.py` specced a bespoke WebSocket schema: our own event names, our
own framing, our own client. That has two costs.

The first is integration. Every client — the dashboard, a CLI, someone else's
tool — has to be written against a schema only Pantheon speaks.

The second is bigger. Agents cannot *drive* a bespoke UI. If the frontend
renders a fixed set of views over a fixed set of messages, an agent that wants
to ask a question, show a comparison, or request a decision has to wait for
someone to build that screen. The interface becomes the bottleneck on what
agents can usefully do.

Two open protocols now cover this, and they solve different halves.

## Decision

**AG-UI is the transport and runtime. A2UI is the payload format for
agent-generated UI.**

This division is the thing people get wrong, so it is stated plainly:

| | AG-UI | A2UI |
|---|---|---|
| **What it is** | An event-based runtime between an agentic backend and a user-facing app | A declarative description of UI, emitted as data |
| **Solves** | Streaming, tool-call visibility, shared-state sync, lifecycle signals, mid-run user input | *What to render*, without shipping code |
| **Analogy** | The pipes | What travels through them, when an agent wants to show something |
| **In Pantheon** | Every event the dashboard receives | Only surfaces an agent asks to render |

Most of what Pantheon emits is **not** A2UI. Lifecycle, findings, tool calls and
state are ordinary AG-UI events. A2UI appears when an agent needs a human to
*see* or *decide* something.

### Versions

| Dependency | Pinned | Why |
|---|---|---|
| `ag-ui-protocol` (Python) | `>=0.1.20,<0.2` | Event types and SSE encoder |
| `@ag-ui/client` (TypeScript) | Phase 4 | `HttpAgent` + middleware. Chosen over `@assistant-ui/react-ag-ui` because we need transport and event middleware, not an opinionated chat UI — Pantheon's dashboard is an investigation console, not a chat window |
| A2UI | **v0.9.1** | v1.0 is a *release candidate*; the specification itself recommends v0.9.1 for production |

**AG-UI's event types are never redefined in `core/contracts/`.** They are
imported from `ag_ui.core`. Restating a published schema is precisely how an
implementation and its specification drift apart, and a test asserts we have not.

## The shared state object is the Investigation

AG-UI's state events carry exactly one thing: the **`Investigation`**.

- `StateSnapshot` at `RunStarted` — the whole Investigation.
- `StateDelta` (RFC 6902 JSON Patch) for every change thereafter.

Naming it is not pedantry. "State", left undefined, is how a second competing
state object gets invented in six months. It also makes **replay** trivial: the
snapshot plus the ordered patches reconstructs any run exactly, which is what
lets an operator scrub back through an incident and see what the platform knew
at each moment.

## Event mapping

Built against the live AG-UI event list rather than any round number — the
protocol has grown Activity and Reasoning families since the "17 event types"
articles.

| Pantheon | AG-UI |
|---|---|
| Investigation created | `RunStarted` + `StateSnapshot` |
| Investigation completed | `RunFinished` |
| Investigation failed | `RunError` |
| Agent dispatched / finished | `StepStarted` / `StepFinished`, `stepName` = codename |
| Agent narration | `TextMessageStart` / `Content` / `End` |
| Connector tool invoked | `ToolCallStart` / `Args` / `End`, then `ToolCallResult` |
| Agent reasoning | `ReasoningStart` … `ReasoningEnd` |
| Finding produced | `StateDelta` |
| Verdict ready | `StateDelta` |
| Delphi `ResolutionRecord` | `StateDelta` |
| Cerberus `AuditEntry` | `StateDelta` |
| Lease expired | `StateDelta` (as a Finding) + an A2UI re-approval surface *when the grant merely expired* |
| Approval required | A2UI surface |
| Credential access requested | A2UI surface |
| **Break-glass invoked** | **`Custom("pantheon.break_glass")`** + `StateDelta` |

### The test for a `Custom` event

The escape hatch is easy to over-use, so the criterion is explicit:

> A `Custom` event is justified only when **the UI must act the moment it
> arrives**, and **that action is not itself an A2UI prompt.**

"Is it ours?" is not the test. Everything here is ours.

### Working through the candidates

Three concepts looked like exceptions. Two are not.

**`ResolutionRecord` — state, no Custom event.** It is attached to the
Investigation (ADR 0004), so it is state by the same argument as findings.
Nothing must happen on arrival: it is rendered in a cost and timing view. There
is no user decision and no interruption.

**`AuditEntry` — state, *except* break-glass.** Most audit events are records:
`REQUESTED`, `GRANTED`, `LEASE_MINTED`, `LEASE_USED`, `ROTATED`. They belong in
the patch stream and nowhere else. `APPROVAL_REQUESTED` is not an exception
either — it is already an A2UI surface, which is the prompt.

`BREAK_GLASS` is different in kind. It revokes every grant and invalidates every
live lease **across every run, immediately**. An open dashboard showing an
investigation that has just been cut off must react now — not render a new row
in an audit list that the operator may not be looking at. Appending it to state
is exactly the "quietly appears in a patch" failure. So: **the Custom event is
the signal, the `AuditEntry` patch is the record.** Both are emitted.

**`LeaseExpired` — state, and no Custom event.** It must surface as a Finding
(ADR 0005), so the record is a `StateDelta`. The counter-argument is that an
expiring lease should prompt re-approval rather than appear silently — and that
is right, but the prompt is **an A2UI surface**, not a Custom event. The escape
hatch is unnecessary because the interactive path already exists.

One nuance falls out of taking that seriously: re-approval is correct when the
grant *expired*, and wrong when it was *revoked*. Prompting a human to re-grant
access that someone deliberately revoked — possibly by break-glass, mid-incident
— would turn a safety control into a nuisance dialog. So the surface is emitted
on expiry only; revocation produces the Finding alone.

**Result: exactly one Custom event.** That is a much stronger interop story than
the three we started with, and it came from applying the state argument
consistently rather than stopping at findings.

## Capability negotiation — Pantheon convention, not specification

A2UI carries `a2uiClientCapabilities` and `a2uiClientDataModel` in **A2A message
metadata**. AG-UI defines no analog, so this is our convention and is labelled as
such.

**The client declares its capabilities in the AG-UI run input, once at run
start.** Direction matters: capabilities flow client → agent, and AG-UI's run
input is the only client → agent channel at run start. The agent therefore knows
what the renderer accepts *before* it emits anything, and never generates a
component that will be rejected.

`A2UIClientCapabilities.components` defaults to the full `A2UIComponentType`
enum, so **the allowlist, the renderer and the advertised capabilities are one
artifact**. There is no second list to keep in step, and a test asserts it.

## Security boundary

> **Agent-generated UI is untrusted data, not code.**

- The host renders A2UI from a **closed component allowlist**
  (`A2UIComponentType`). No arbitrary HTML, no script execution, no free-form
  styling.
- **No agent-rendered component may request credentials or approvals outside
  the Cerberus and Approval Gate paths.** A surface is a *rendering* of a
  request those systems already understand; it carries no authority of its own,
  and a returning action is re-validated against the request it claims to
  answer.
- **Identity is set by the orchestrator, never by the agent.** A2UI calls this
  out explicitly: `iconUrl` and `agentDisplayName` live on `A2UISurface`, not on
  `A2UIComponent`, so no agent can present itself as another agent or as
  Pantheon itself. A test asserts the fields are absent from the component
  contract.

### What is excluded from the allowlist, and why

The catalog is chosen for what it **cannot** be abused to do.

| Excluded | Reason |
|---|---|
| `Image`, `Video`, `AudioPlayer` | Each fetches an agent-supplied URL. That outbound request **is** an exfiltration channel: the agent encodes what it learned into the URL and the browser delivers it. Excluded despite being the most obviously useful components for an incident console. |
| `Modal` | An agent that can force a modal can overlay a convincing fake credential prompt. Credential requests travel one path only. |
| `Tabs`, `Slider` | No current use. The allowlist grows on demand, never speculatively. |

Allowed: `Row` `Column` `Card` `List` · `Text` `Icon` `Divider` · `TextField`
`CheckBox` `ChoicePicker` `DateTimeInput` · `Button`.

## ⚠️ Unresolved: the A2UI-over-AG-UI envelope

AG-UI advertises day-zero A2UI compatibility, and A2UI names AG-UI as a
transport. But **A2UI v0.9.1 defines its message mapping against A2A message
Parts**, and neither specification documents a canonical AG-UI envelope for an
A2UI payload. Published examples improvise — one uses a `GenerativeUI` event with
`format: "a2ui"` alongside a `MessageDelta` event, and `MessageDelta` is not an
AG-UI event type at all.

Pantheon emits A2UI as an AG-UI **`Custom` event named `a2ui`**, one A2UI message
per event. This is a guess, and it is marked as one.

**The guess lives in exactly one place**: `api/agui/a2ui_channel.py`. If a
canonical envelope is standardised, two things change and nothing else:
`EVENT_NAME` (or the choice of `Custom`), and `to_wire()` (the payload shape).
`core/ui/` builds surfaces, `translator.py` decides *when* to emit, and only the
seam decides *how*. A test asserts no other module hardcodes the envelope.

The cost of being wrong is one function and one constant — bounded and visible,
which is the entire point of isolating it. Tracked in the ROADMAP.

## Cross-check with ADR 0005

An A2UI payload is **agent-authored and reaches a human**, which makes it a sink
in exactly the sense ADR 0005 means.

- **Redaction** runs on surfaces before emission. The schema scan catches
  secret-shaped *field names*; it cannot catch a secret pasted into a `Text`
  component's body, and redaction is what covers that. A test builds a surface
  containing a planted secret and asserts it does not survive.
- **The schema scan** covers `core/contracts/ui.py` like every other contract.
- Cerberus `AccessRequest` surfaces carry the stated reason, exact scope, lease
  TTL and investigation id — the same fields ADR 0005 requires, rendered rather
  than restated.

## Dashboard impact (branch 4)

- `dashboard/lib/agui/` — `@ag-ui/client` `HttpAgent`, plus middleware for
  logging and reconnection.
- `dashboard/components/a2ui/` — the renderer, switching **exhaustively over the
  generated `A2UIComponentType`**, rejecting anything else.
- The four route pages consume the AG-UI event stream rather than bespoke
  WebSocket messages.

## Consequences

**Good**

- Any AG-UI-compatible client can drive Pantheon; the dashboard stops being the
  only possible frontend.
- Agents can render UI without a frontend change, within a boundary that makes
  that safe.
- Replay is a property of the design rather than a feature to build.
- One Custom event means near-total standard-protocol coverage.

**Costs**

- Two specifications to track, one of them pre-1.0 and moving.
- The envelope gap is real until a spec settles it.
- The allowlist will feel restrictive — excluding `Image` from an incident
  console is a genuine loss, accepted deliberately.
- `ag-ui-protocol` has a known Python/TypeScript SDK mismatch on
  `ReasoningMessageStartEvent.role` (`"assistant"` vs `"reasoning"`,
  [ag-ui#1169](https://github.com/ag-ui-protocol/ag-ui/issues/1169)). We are
  pinning a dependency with a live interop bug; tracked in the ROADMAP.

## Alternatives considered

| Option | Why not |
|---|---|
| **Keep the bespoke WebSocket schema** | Every client is custom, and agents cannot generate UI at all. |
| **AG-UI only, no A2UI** | Agents could stream text and tool calls but never ask for a rendered decision; the Approval Gate stays a hardcoded screen. |
| **A2UI only, over our own transport** | Loses streaming, state sync and lifecycle — the parts AG-UI already solves — and keeps the custom-client problem. |
| **Ship raw HTML from agents** | The exfiltration and impersonation surface this ADR exists to close. |
| **Wait for the envelope to be standardised** | Blocks the dashboard indefinitely on someone else's spec, when the exposure is one function. |

## Phase plan

| Phase | Delivers |
|---|---|
| **0** | Contracts, structure, allowlist, all guards; `api/ws/` removed |
| **4** | AG-UI endpoint and translator, A2UI surfaces for Approval Gate and Cerberus, dashboard client and renderer |
| **5** | Replay from snapshot + patches; revisit the envelope and A2UI v1.0 |
