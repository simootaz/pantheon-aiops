# ADR 0001 — Object storage: MinIO, S3-compatible interface, no cloud dependency

- **Status:** Accepted
- **Date:** 2026-08-14
- **Decided on branch:** `feature/go-workspace`
- **Applies from:** Phase 6 (`feature/deploy-skeleton`) onward

## Context

Pantheon needs durable object storage for three things: generated reports
(Clio), investigation artifacts (evidence bundles, flame graphs, log excerpts)
and database/cluster backups.

The obvious default would be AWS S3. That default is wrong for this project.
Pantheon is an AIOps platform that must be demonstrable and operable **fully
self-hosted, with zero cloud accounts** — on a laptop, in an air-gapped lab, or
inside a customer's own cluster. A hard dependency on AWS would make the local
Compose stack un-runnable without credentials and would couple our deployment
story to one vendor.

At the same time, some operators *will* want to point Pantheon at real S3, or at
Ceph RADOS Gateway, Wasabi, Backblaze B2, or Cloudflare R2.

## Decision

**MinIO is the default object storage layer everywhere, and the S3 API is the
only interface we program against.**

1. **Compose** ships a `minio` service (API `:9000`, console `:9001`) plus a
   one-shot `minio-init` container that uses `mc` to create the three buckets:
   `pantheon-reports`, `pantheon-artifacts`, `pantheon-backups`.
2. **Helm** exposes a `minio:` block in `values.yaml`, `enabled: true` by
   default, with `external.endpoint`, `external.region` and `existingSecret` so
   a real S3 or any S3-compatible provider can be substituted **without touching
   application code**. Templates live behind `.Values.minio.enabled`.
3. **Terraform** module `object-storage/` (renamed from `s3/`) is
   provider-shaped, not AWS-shaped. `envs/dev` targets MinIO; `envs/prod`
   stays pluggable.
4. **Application code** uses `boto3` (or `minio-py`) against a configurable
   `S3_ENDPOINT_URL`. No AWS endpoint or region is ever hardcoded.
5. **Backups** — both Velero and the Postgres backup CronJob target MinIO.

### Configuration surface

Declared in `.env.example`:

| Variable | Purpose |
|---|---|
| `S3_ENDPOINT_URL` | Full endpoint URL; MinIO locally, anything S3-compatible elsewhere |
| `S3_ACCESS_KEY` | Access key |
| `S3_SECRET_KEY` | Secret key |
| `S3_REGION` | Region string; MinIO accepts any value |
| `S3_BUCKET_REPORTS` | Generated reports |
| `S3_BUCKET_ARTIFACTS` | Investigation artifacts |
| `S3_BUCKET_BACKUPS` | Database and cluster backups |
| `S3_USE_SSL` | TLS toggle; `false` for the local stack |

## The rule this creates

> **Any S3-compatible endpoint must work.** Do not couple to MinIO's own SDK
> features beyond what the S3 API gives you.

Concretely: no `mc admin` calls from application code, no MinIO-specific bucket
notification or versioning extensions, no reliance on MinIO's erasure-coding
behaviour. If a capability is not in the S3 API, it does not belong in
application code. `mc` is permitted **only** in the Compose `minio-init`
one-shot and in operator-facing scripts under `deploy/scripts/`, never in
`core/`, `agents/`, `api/` or `connectors/`.

## Consequences

**Good**

- `make up` works on a fresh clone with no cloud account and no credentials.
- One code path for local, CI, and production.
- Operators can swap in their own provider through config alone.
- Air-gapped and on-premise deployments are first-class, not an afterthought.

**Costs**

- MinIO becomes a component we run and upgrade in the default stack.
- We forgo AWS-native conveniences (IAM roles for service accounts, S3 Select,
  lifecycle policies expressed in Terraform against AWS resources). Lifecycle
  and retention must be expressed in a provider-neutral way.
- Credentials are static keys by default rather than short-lived role
  credentials. Production overlays should mount them from a sealed secret —
  see `deploy/security/sealed-secrets/`.

## Alternatives considered

| Option | Why not |
|---|---|
| **AWS S3 directly** | Requires a cloud account to run anything; breaks the self-hosted goal outright. |
| **Local filesystem / PVC** | No shared access across replicas, no presigned URLs, and backups would need a second mechanism. |
| **Ceph RADOS Gateway as default** | Correct interface, but far heavier to run locally than MinIO. Still supported, since it speaks S3. |

## Implementation checklist

Applied on `feature/deploy-skeleton`, 2026-08-15.

- [x] `deploy/compose/docker-compose.yml` + `.dev.yml` — `minio` and `minio-init` services
- [x] `deploy/helm/pantheon/values.yaml` — `minio:` block
- [x] `deploy/helm/pantheon/templates/minio-*.yaml` behind `.Values.minio.enabled`
- [x] `deploy/terraform/modules/s3/` → `modules/object-storage/`, made provider-shaped
- [x] `deploy/terraform/envs/dev` → MinIO; `envs/prod` pluggable
- [x] `.env.example` — the eight `S3_*` variables
- [x] `deploy/backup/` — Velero and Postgres CronJob target MinIO

### Verified on application

`helm template` proves the passthrough rather than asserting it:

| Values | `S3_ENDPOINT_URL` renders as | MinIO objects rendered |
|---|---|---|
| default | `http://pantheon-pantheon-minio:9000` | 8 |
| `values-prod.yaml` | `https://s3.example.com` | 0 |

Application configuration is identical in both cases - only the endpoint moves,
which is the whole point of the decision.
