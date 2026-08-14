# Pantheon Roadmap

> **Phase: 0 - Scaffold & Tooling.** The full phase breakdown with exit criteria
> is written on branch `feature/docs-baseline`. The authoritative phase list
> currently lives in [CLAUDE.md](CLAUDE.md#phase-roadmap).

## Phase 0 branch order

Phase 0 is delivered as eight feature branches. They were **reordered after
branch 1**: branch 3 was pulled ahead of branch 2.

**Reason:** the Python toolchain (`uv`, Python 3.12) was not yet installed, so
`feature/python-tooling` could not have its gate verified, while Go 1.23 was
already present and `feature/go-workspace` could be verified in full. Git Flow
is unaffected — the branches are independent.

| Order | Branch | Status |
|---|---|---|
| 1 | `feature/repo-skeleton` | ✅ merged |
| 2 | `feature/go-workspace` | ✅ merged *(was 3rd)* |
| 3 | `feature/python-tooling` | ⏳ next *(was 2nd)* |
| 4 | `feature/dashboard-scaffold` | ⏳ |
| 5 | `feature/codegen-pipeline` | ⏳ |
| 6 | `feature/deploy-skeleton` | ⏳ |
| 7 | `feature/ci-workflows` | ⏳ |
| 8 | `feature/docs-baseline` | ⏳ |

## Definition of done — Phase 0

On a fresh clone, all of the following must pass.

| Language | Commands |
|---|---|
| Python | `make install && make lint && make typecheck && make test` |
| Go | `make lint-go`, `make test-go`, `go build github.com/simootaz/pantheon-aiops/...` |
| TypeScript | `pnpm --dir dashboard build` |
| Deploy | `helm lint deploy/helm/pantheon`, `terraform fmt -check`, `docker compose config` |
| Docs | CLAUDE.md accurately describes every directory that exists |

> **Note on the Go commands.** `go build ./...` is *not* used and must not be
> reintroduced. The repo root has no `go.mod`, so the pattern is invalid there,
> and adding a root module would not help — nested modules are pruned from a
> parent's package walk, so it would report success while building nothing. The
> three commands above cover all four modules and all eight packages.

## Deferred decisions

Things deliberately set to a scaffold-friendly value now, to be tightened later.

| Item | Now | Target | When |
|---|---|---|---|
| Object storage | — | MinIO everywhere, S3-compatible only | Phase 6 — see [ADR 0001](docs/adr/0001-object-storage-minio.md) |
| `unparam` / `nilnil` Go linters | disabled | enabled | Phase 6, once the Go connector is real |

<!-- TODO: Phase 0 - full roadmap with per-phase exit criteria on branch feature/docs-baseline -->
