# Admission policies

Kyverno or OPA Gatekeeper policies enforcing Pantheon's deployment invariants:
non-root containers, read-only root filesystems, no `:latest` tags in
production, and required resource limits.

_Phase: 7 - Production Hardening_

<!-- TODO: Phase 7 - author the policy set and wire it into CI -->
