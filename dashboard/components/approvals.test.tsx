/**
 * What the approval card must show before anyone can press anything.
 *
 * The failure being guarded is a rendered one: a card that shows an id and two
 * buttons is the prompt `core/ui/approval.py` refuses to emit, and a gate
 * answered by reflex records a decision nobody made. Asserted against the
 * output, because that is where "did the approver see the blast radius" is
 * answerable.
 *
 * Phase: 4 - Delivery Flow
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PendingApproval } from "@/lib/api";
import type { Action } from "@/types/generated/contracts";
import { ApprovalCard } from "./approvals";

function action(overrides: Partial<Action> = {}): Action {
  return {
    id: "22222222-2222-2222-2222-222222222222",
    target: { kind: "deployment", name: "checkout", namespace: "shop" },
    operation: "rollout_restart",
    parameters: {},
    blast_radius: "namespace",
    reason: "pods are OOMKilling every four minutes",
    rollback: "kubectl rollout undo deployment/checkout",
    proposed_by: "zeus",
    proposed_at: "2026-09-04T10:00:00Z",
    dry_run: false,
    ...overrides,
  } as Action;
}

function approval(overrides: Partial<PendingApproval> = {}): PendingApproval {
  return {
    id: "33333333-3333-3333-3333-333333333333",
    action_id: "22222222-2222-2222-2222-222222222222",
    proposed_by: "zeus",
    opened_at: "2026-09-04T10:00:00Z",
    expires_at: "2026-09-04T10:10:00Z",
    answered_by: null,
    reason: null,
    rule: "default-requires-a-human",
    because: "no rule classified this operation",
    action: action(),
    ...overrides,
  };
}

describe("what the card shows", () => {
  it("shows the target, the blast radius, the rollback and the reason", () => {
    // The four fields the A2UI card carries. An approver missing any one of
    // them is deciding on less than the surface would have shown - which would
    // make the argument in core/ui/approval.py true in Python and false here.
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={vi.fn()} />
      </ul>,
    );

    // Matched on the namespace, not on "checkout": the workload name also
    // appears in the rollback command, and a substring that matches two
    // elements would pass even if the target field vanished.
    expect(screen.getByText(/deployment\/checkout in shop/)).toBeDefined();
    expect(screen.getByText("namespace")).toBeDefined();
    expect(screen.getByText(/rollout undo/)).toBeDefined();
    expect(screen.getByText(/OOMKilling/)).toBeDefined();
  });

  it("says out loud when an Action is not a dry run", () => {
    // The difference between rehearsing and doing it, and the one an approver
    // most needs at the moment of pressing.
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={vi.fn()} />
      </ul>,
    );

    expect(screen.getByText(/will change the system/)).toBeDefined();
  });

  it("names the rule and why it fired", () => {
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={vi.fn()} />
      </ul>,
    );

    expect(screen.getByText(/no rule classified this operation/)).toBeDefined();
  });
});

describe("a request with no recorded Action", () => {
  it("is listed but offers no buttons", () => {
    // Still shown - hiding it would lose a request that is genuinely waiting.
    // Not answerable - a button beside an id with no content is "approve
    // action 7f3a?", which is the whole thing being avoided.
    render(
      <ul>
        <ApprovalCard approval={approval({ action: null })} onAnswer={vi.fn()} />
      </ul>,
    );

    expect(screen.getByText(/22222222/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("is the exception - a request with one does offer them", () => {
    // The control. A card that never rendered buttons would pass the assertion
    // above for the wrong reason.
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={vi.fn()} />
      </ul>,
    );

    expect(screen.getByRole("button", { name: "Approve" })).toBeDefined();
  });
});

describe("answering", () => {
  it("approves with the Action that was displayed", () => {
    // Not the id. The endpoint re-validates against content, and sending
    // anything but the object on screen would answer a different act.
    const onAnswer = vi.fn();
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={onAnswer} />
      </ul>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(onAnswer).toHaveBeenCalledWith(true, approval().action, "");
  });

  it("will not send a rejection with no reason", () => {
    // A proposer told only "no" learns nothing about what to change. The API
    // accepts an empty reason; this refuses to offer one.
    const onAnswer = vi.fn();
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={onAnswer} />
      </ul>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Confirm rejection" });

    expect(confirm.hasAttribute("disabled")).toBe(true);
    fireEvent.click(confirm);
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("sends the rejection once a reason is written", () => {
    // The control on the previous test. A confirm button disabled forever
    // would pass it and make rejection impossible.
    const onAnswer = vi.fn();
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={onAnswer} />
      </ul>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "restart hides the leak; find it first" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));

    expect(onAnswer).toHaveBeenCalledWith(
      false,
      approval().action,
      "restart hides the leak; find it first",
    );
  });

  it("trims a reason of nothing but whitespace rather than accepting it", () => {
    const onAnswer = vi.fn();
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={onAnswer} />
      </ul>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });

    expect(screen.getByRole("button", { name: "Confirm rejection" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("shows the gate's refusal on the card rather than swallowing it", () => {
    // A 409 - already answered, expired, self-approved. The other rows are
    // still answerable, so it belongs on this card and not on the page.
    render(
      <ul>
        <ApprovalCard
          approval={approval()}
          onAnswer={vi.fn()}
          error="zeus proposed this action and cannot approve it"
        />
      </ul>,
    );

    expect(screen.getByText(/cannot approve it/)).toBeDefined();
  });

  it("does not accept a second press while one answer is in flight", () => {
    render(
      <ul>
        <ApprovalCard approval={approval()} onAnswer={vi.fn()} busy={true} />
      </ul>,
    );

    expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(true);
  });
});
