"""The four-step resolution cascade.

per-task override -> per-agent binding -> tier default -> global default.

The first binding that *satisfies the declared requirements* wins; a binding
that does not is skipped rather than used. An explicit override that cannot
satisfy them is an error, not a silent downgrade - otherwise an override becomes
a way to quietly break an agent.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement the cascade against the capability matrix
