# Sealed secrets

Encrypted secrets safe to commit, decrypted in-cluster by the Sealed Secrets
controller.

Two secrets matter today, and **neither may ever be committed in plaintext**:

| Secret | Holds | Consumed by |
|---|---|---|
| `pantheon-object-storage` | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | `minio.external.existingSecret` |
| `pantheon-llm-credentials` | one key per provider `secretRef` | `delphi.existingSecret` |

Seal one with:

```bash
kubectl create secret generic pantheon-llm-credentials \
  --from-literal=GATEWAY_PRIMARY_API_KEY=... --dry-run=client -o yaml \
  | kubeseal --format yaml > pantheon-llm-credentials.sealed.yaml
```

A provider credential that reaches an Investigation record, a log line or a
trace is a security bug - see [ADR 0005](../../../docs/adr/0005-credential-brokering.md).
Provider API keys are Cerberus credentials like any other.

_Phase: 7 - Production Hardening_

<!-- TODO: Phase 7 - commit the sealed secrets for each environment -->
