# Repository Convergence Design

## Goal

Reduce repository and branch sprawl while preserving documented public
contracts. Land the unmerged Open Knowledge Framework (OKF) capability on the
current trunk without restoring legacy trees removed by repository cleanup.

`master` remains the only development trunk.

## Constraints

- Preserve documented APIs, schemas, ports, and CLI behavior.
- Internal imports, package layouts, and Compose wiring may change.
- Merge only green PRs; do not bypass required checks.
- Keep each change reviewable and independently reversible.
- Do not combine formatting, dependency updates, or unrelated refactors with
  convergence work.
- Remove a live service only after all runtime, CI, Compose, import, and
  documentation callers have migrated.

## Branch Convergence

Create annotated archive tags before deleting residual remote branches:

- Tag `chore/repo-cleanup-phase-1` at its final commit, then delete it because
  PR #252 already merged its useful tree.
- Tag `ide/category-leader-roadmap-047e` at its final commit. Keep the branch
  until every selected OKF transplant PR has merged, then delete it.

Do not merge or range-cherry-pick the OKF branch. It is behind `master`, changes
800 files relative to the current tree, and would restore paths removed
by PR #252. Reconstruct selected final behavior on branches created from
`master`.

## Delivery Sequence

### 1. OKF foundation

Port the final governed-bundle models, parser, registry, provenance fixtures,
validation CLI, deterministic exporter, and empty shared/tenant bundle roots.
Approved concepts must have immutable source provenance. Parsing must reject
path traversal, cross-tenant links, duplicate identifiers, stale provenance,
and missing targets.

### 2. OKF retrieval

Add tenant-safe indexing and retrieval in this order:

1. Exact concept match.
2. Bounded graph traversal.
3. Existing hybrid retrieval fallback.

Authority is tenant OKF, shared OKF, then memo RAG. Conflicting or stale
authoritative concepts cause abstention. Registry activation and index
replacement are atomic.

### 3. OKF runtime

Add startup validation, atomic administrative reload, sanitized health and
readiness states, configuration limits, image packaging, and read-only tenant
overlays. A failed reload keeps the previous active generation.

Only the canonical deployment surfaces are changed:

- `infra/deploy/docker-compose.yml`
- `infra/deploy/helm/fraud-stack`
- `services/investigation-agent/Dockerfile`
- `.github/workflows/ci.yml`

### 4. Copilot grounding

Bind claims to exact concept IDs, evidence IDs, and supporting tool calls.
Citations may resolve only references selected for the current tenant-scoped
turn. Invalid tool-bound claims are withheld or downgraded; strict mode
abstains when grounding fails.

### 5. Durable AgentRun and review audit

Land durable AgentRun persistence and append-only review history separately
from core OKF. Tenant-scoped retrieval is mandatory. Local SQLite deployment
must remain single-replica with persistent storage and a non-overlapping
rollout strategy.

### 6. Immediate dead-code removal

Remove only after confirming no current references:

- `services/rule-engine`, which is a tombstone for
  `packages/tarka-rule-engine`.
- `services/agent`, after either moving its still-useful hardware guard into
  `services/shadow_agent` or proving the guard is obsolete.

### 7. Low-risk live consolidation

- Move the private `services/integration` helper package into
  `services/integration-ingress`, temporarily retaining its import path.
- Move in-process `services/shadow` hooks under orchestrator ownership while
  retaining `shadow.hooks.*` compatibility. Keep the production
  `services/shadow_agent` HTTP service and local `tools/shadow` application
  separate.

### 8. Higher-risk live consolidation

Perform these as independent migrations:

- Replace deprecated `services/rule_engine` callers with
  `packages/tarka-rule-engine` through `services/decision-api`.
- Retire `services/core_v2` after migrating the quarantined streams profile and
  any batch sidecars.
- Resolve the `services/analytics` and
  `services/orchestrator/analytics` namespace collision under one package.
- Converge `services/data-platform` routes onto `services/data-plane` while a
  temporary compatibility listener preserves port 8014 and existing storage
  semantics.
- Fold online event-ingest and analytics-sink deployment surfaces into
  data-plane without conflating them with offline batch ingest or evidence
  persistence.

### 9. Source-tree canonicalization

Canonicalize Python packages on `src/<package>` only after all callers use the
canonical imports. Treat `services/ingestor` separately because both flat and
package imports are live.

## Compatibility Policy

Documented OpenAPI routes, response schemas, ports, environment variables, and
CLI behavior remain stable during migration. Internal callers move to canonical
packages. High-risk migrations retain a compatibility adapter for one release,
with an explicit removal gate.

The OKF public contract includes:

- `GET /v1/health`
- `GET /v1/ready`
- authenticated `GET /v1/admin/health/details`
- authenticated `POST /v1/admin/okf/reload`
- tenant-scoped exact citations using schema version `1.0.0`
- tenant-scoped AgentRun retrieval when audit persistence is enabled

## Verification and Merge Gates

Each delivery unit uses a separate PR with the smallest focused regression
check plus the repository-required CI suite. Representative checks are:

- OKF parser, registry, exporter, retrieval, end-to-end, security, and citation
  tests.
- Bundle validation against `knowledge/shared`.
- Ruff checks for touched Python packages.
- Helm lint/template and Compose configuration checks.
- Investigation-agent image build.
- Targeted tests for each migrated service and its compatibility contract.

A deletion PR must demonstrate zero references from runtime code, CI, Compose,
imports, package manifests, contracts, and current documentation.

## Rollback

- Archive tags preserve both residual branch tips.
- Every convergence unit is independently revertible.
- Compatibility adapters remain for one release on high-risk migrations.
- OKF reload failure retains the prior generation.
- The OKF source branch is deleted only after all selected transplant PRs have
  merged and their tests are green.

## Non-Goals

- Restoring PR #252-deleted legacy trees.
- Combining unrelated decision-engine hardening with OKF.
- Merging services solely because their names are similar.
- Replacing documented public contracts as part of repository cleanup.
- Broad formatting, lockfile churn, or speculative abstractions.
