"""Enforcing `AgentBudget.max_tokens` against Delphi's token counts.

WHY THIS ONLY EXISTS NOW
--------------------------
`max_tokens` sat on every manifest since Phase 0, enforced nowhere, and
`tests/unit/test_agent_runtime.py` asserted that nothing read it. That was
deliberate: nothing consumed tokens, so there was no meter, and an enforcement
path that cannot be tested is the unfailable-guard class one level up.

Delphi has landed and `Completion` carries `prompt_tokens` and
`completion_tokens`. The meter exists, so the field can be connected - and the
guard that kept it disconnected is retired in the same commit, replaced by tests
that fail when enforcement is removed.

THE CEILING IS CHECKED BEFORE THE CALL, NOT AFTER
---------------------------------------------------
A meter that only charges after the fact cannot stop anything: the tokens are
already spent and the money is already gone. So a request is refused when the
remaining budget could not cover it in the worst case - the prompt as counted,
plus the ceiling the caller asked the provider for.

That is deliberately pessimistic. The alternative is to assume a completion will
be shorter than the caller allowed, which is an assumption about the model's
output made before the model has produced any.

REFUSAL, NOT DOWNGRADE
------------------------
Running out of budget stops the agent. It does not switch to a cheaper model or
silently shorten the request - the same argument as `Unresolvable` and
`BudgetExceeded` in the gateway. An agent quietly given less produces worse
output with no signal that anything changed, and the reader has no way to
connect the two.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass, field


class TokenBudgetExceeded(RuntimeError):
    """The run has spent, or would spend, more tokens than its manifest allows.

    A `RuntimeError` rather than an `AgentDegraded`: agents do not raise this,
    the runtime does, and `BaseAgent.run` turns it into a DEGRADED Finding the
    same way it does a tool budget or a timeout. An agent that caught this and
    carried on would be spending a budget it had already exhausted.
    """


@dataclass
class TokenMeter:
    """What one agent run has spent, and what it is allowed.

    One per run. A meter shared across runs would let a busy investigation
    exhaust a quiet one's budget, and the failure would look like a flaky agent.
    """

    ceiling: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Every charge, in order. Kept because "which call blew the budget" is the
    #: first question asked, and a running total cannot answer it.
    charges: list[tuple[str, int]] = field(default_factory=list)

    @property
    def spent(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def remaining(self) -> int:
        return max(self.ceiling - self.spent, 0)

    def check(self, *, requested_by: str, worst_case: int) -> None:
        """Refuse now if this request could not fit. Raises or returns.

        `worst_case` is what the request could cost, not what it probably will.
        A budget enforced against an estimate is a budget that is exceeded
        whenever the estimate is wrong, which is the case nobody tests.
        """
        if worst_case > self.remaining:
            raise TokenBudgetExceeded(
                f"{requested_by} needs up to {worst_case} tokens and has "
                f"{self.remaining} of its {self.ceiling} left (spent {self.spent}). "
                "Stopping rather than shortening the request or moving to a "
                "smaller model, either of which produces worse output with no "
                "signal that anything changed."
            )

    def charge(self, *, requested_by: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Record what a call actually cost.

        Charged even when it takes the meter past its ceiling. The tokens were
        spent, and a meter that refused to record an overrun would report a
        total lower than the bill - the next `check` is what stops the run.
        """
        self.prompt_tokens += max(prompt_tokens, 0)
        self.completion_tokens += max(completion_tokens, 0)
        self.charges.append((requested_by, max(prompt_tokens, 0) + max(completion_tokens, 0)))

    def as_dict(self) -> dict[str, object]:
        """For a DEGRADED Finding's tags, and for anything reporting spend."""
        return {
            "ceiling": self.ceiling,
            "spent": self.spent,
            "remaining": self.remaining,
            "calls": len(self.charges),
        }
