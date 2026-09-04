"""Guardrails: the policy, approval and budget layer every write Action passes through.

THE CHAIN, IN ORDER
---------------------
`policy.evaluate` decides; `approval_gate` holds what needs a person;
`executor.execute` is the only path from a proposed Action to a system that
changes, and it re-validates the approval against the Action *as it is now*.
`budget` bounds what a run may spend before it starts, not after.

The order matters and is not configurable. An executor that consulted the
approval before the policy would honour an approval for something policy denies.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from core.guardrails.approval_gate import ApprovalGate, digest_of, may_execute
from core.guardrails.budget import TokenBudgetExceeded, TokenMeter, within_cost_ceiling
from core.guardrails.executor import NotPermitted, execute
from core.guardrails.policy import Decision, Ruling, evaluate

__all__ = [
    "ApprovalGate",
    "Decision",
    "NotPermitted",
    "Ruling",
    "TokenBudgetExceeded",
    "TokenMeter",
    "digest_of",
    "evaluate",
    "execute",
    "may_execute",
    "within_cost_ceiling",
]
