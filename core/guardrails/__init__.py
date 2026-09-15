"""Guardrails: the policy, approval and budget layer every write Action passes through.

THE CHAIN, IN ORDER
---------------------
`policy.evaluate` decides; `proposal.propose` acts on that decision and opens
the request when a person is needed; `approval_gate` holds it until one answers;
`executor.execute` is the only path from a proposed Action to a system that
changes, and it re-validates the approval against the Action *as it is now*.
`budget` bounds what a run may spend before it starts, not after.

Proposing and spending are two functions because they happen at two moments.
`propose` opens a request and returns; `execute` takes the answer and runs. A
single call doing both would have to block on a human, and a retry would open a
second request for the same act.

The order matters and is not configurable. An executor that consulted the
approval before the policy would honour an approval for something policy denies.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from core.guardrails.approval_gate import ApprovalGate, digest_of, may_execute
from core.guardrails.budget import TokenBudgetExceeded, TokenMeter, within_cost_ceiling
from core.guardrails.executor import NotPermitted, execute
from core.guardrails.policy import Decision, Ruling, evaluate
from core.guardrails.proposal import Proposal, propose, propose_all

__all__ = [
    "ApprovalGate",
    "Decision",
    "NotPermitted",
    "Proposal",
    "Ruling",
    "TokenBudgetExceeded",
    "TokenMeter",
    "digest_of",
    "evaluate",
    "execute",
    "may_execute",
    "propose",
    "propose_all",
    "within_cost_ceiling",
]
