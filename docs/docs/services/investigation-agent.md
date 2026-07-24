# Investigation Agent

LLM **copilot** for investigations: tool-use loop against Case API, Graph Service, Decision API, and optional knowledge/RAG. Ships deterministic **evidence summary** and export paths for review workflows.

**Port:** 8006  
**Framework:** Python / FastAPI

---

## Highlights

| Concern | Entry point |
|---------|-------------|
| Chat (sync / SSE) | `POST /v1/chat`, `POST /v1/chat/stream` |
| Evidence summary (OSS #40) | `POST /v1/evidence/summary` — no LLM; structured `citations[].resolves_to`, `next_actions`, optional typology drivers |
| Operator checklist | Public stable-code probes: `GET /v1/ready`, `GET /v1/health`; authenticated diagnostics: `GET /v1/setup`, `GET /v1/admin/health/details` |
| Integration contract | `GET /v1/integration` |
| Trust / ops data source | Console strip calls Decision API **`GET /v1/ops/evaluation-posture`** + **`GET /v1/slo`** (not this service); see [API Reference — Trust / ops readiness](../api-reference.md#trust-ops-readiness) |

!!! note "Contracts & guides"

    OpenAPI: `contracts/openapi/investigation-agent.yaml`  
    Project narrative: [Investigation Agent project](../projects/investigation-agent-project.md) · [Saarthi Pro vs OSS](../guides/saarthi-pro-vs-oss.md) · [Collaboration chat & cloud](../guides/investigation-collaboration-chat-aws-azure.md)

---

## Configuration

Requires **`OPENAI_API_KEY`** (or compatible base URL) for LLM rounds. Optional upstreams: **`CASE_API_URL`**, **`GRAPH_SERVICE_URL`**, **`DECISION_API_URL`**. Production hardening: **`infra/deploy/docker-compose.production-hardening.yml`**, `COPILOT_PRODUCTION_MODE`, and related envs — see the project doc.

### AgentRun persistence and scaling

Every normal, refused, and deterministic-fallback run is stored under
`INVESTIGATION_DATA_DIR`. Compose mounts that directory on the
`investigation_agent_data` named volume. The supported Helm charts default to
`agentRunPersistence.mode: local-sqlite`, create or mount a PVC, and require
`replicaCount: 1` (the lite chart uses the equivalent `replicas: 1`).
Those Deployments use the `Recreate` rollout strategy so two pods never overlap
on the same local SQLite PVC during upgrades.

SQLite cannot provide coherent writes across investigation-agent pods. Before
horizontal scaling, migrate AgentRun and review-state persistence to an external shared AgentRun store
with tenant-scoped reads and transactional review updates, deploy a chart wired
to that store, and only then raise the replica count. The stock charts
deliberately fail rendering when local SQLite is configured above one replica.

### OKF curated knowledge bundles

The image ships only the approved shared OKF bundle at
`/app/knowledge/shared`. Tenant overlays are not baked into the image; operators
mount approved tenant revisions at `/var/lib/tarka/knowledge/tenants/<tenant_id>`.

Reference deployment env:

```dotenv
OKF_ENABLED=true
OKF_SHARED_ROOT=/app/knowledge/shared
OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants
OKF_ADMIN_API_KEYS=okf-admin-key
OKF_MAX_LINK_DEPTH=2
OKF_MAX_CONCEPTS=24
```

`POST /v1/admin/okf/reload` requires a key that is present in both
`API_KEYS` and `OKF_ADMIN_API_KEYS`. The same key must also have tenant scope in
`API_KEY_TENANT_MAP` (or the deployment must use an equivalent authenticated
tenant binding configuration), so granting general service access does not grant
OKF reload privileges.

#### Proposed staging vs approved promotion

Staging exports are proposed content and must not replace the active shared
root directly:

```bash
python services/investigation-agent/scripts/export_okf_bundle.py \
  --rules-dir services/legacy_v1_decision_api/rules \
  --output /tmp/okf-staging/shared \
  --include-playbooks
```

Review staged Markdown and convert accepted concepts to `approval_status:
approved` with an approved revision. Normal audits remain evidence; landmark
cases require sanitization and human review before they can become concepts.
Promotion is a Git approval step: copy only the approved shared revision into
`knowledge/shared`, review the diff, and merge via the normal branch protection
path.

Export a sanitized landmark input into a complete tenant staging bundle:

```bash
python services/investigation-agent/scripts/export_okf_bundle.py \
  --landmark-input /secure/review/case-opaque-22.json \
  --tenant-id t1 \
  --output /tmp/okf-staging/tenants/t1
```

The input must not contain `source_content_hash`. The command validates every
accepted textual field for PII, then generates the concept, an independent
canonical source snapshot, and `source-manifest.json` together. Promote all
three artifacts as one reviewed revision; never paste or manually trust a hash.

Tenant overlays follow the same approval rule but are mounted by operators under
`OKF_TENANT_ROOT`; they are validated against the promoted shared root:

```bash
python services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
python services/investigation-agent/scripts/validate_okf_bundle.py \
  /var/lib/tarka/knowledge/tenants/t1 \
  --scope tenant \
  --tenant-id t1 \
  --shared-root knowledge/shared
```

Tenant links to shared concepts use logical Markdown hrefs such as
`/shared/rules/high-amount.md`. The validator resolves those links with
`--shared-root`; tenant links outside their own overlay or the approved shared
bundle fail validation.

#### Retrieval output, readiness, and rollback

`search_knowledge` returns approved OKF hits before memo RAG. Exact concept
matches appear with `retrieval_mode` containing `exact`; linked concepts appear
through `retrieval_path`; memo fill-ins appear as `memo_rag`. If embeddings are
unavailable, retrieval falls back to keyword search and reports
`keyword_fallback`. OKF hits include `concept_id`, `content_hash`,
`evidence_ids`, and `retrieval_path` so citations can resolve exact concept and
evidence IDs.

`GET /v1/ready` is `ready` only when RAG and every other enabled knowledge path
are healthy. OKF may be disabled without degrading readiness; when enabled, an
OKF or RAG failure returns sanitized `not_ready` with HTTP 503.
`POST /v1/admin/okf/reload` is fail-closed for invalid bundles: an invalid
reload reports issues and keeps the prior active snapshot.

Admin reload is process-local. In multi-replica Kubernetes deployments, promote
the approved shared bundle/PVC revision and perform a rolling restart (or an
equivalent per-replica reload orchestration) so every investigation-agent replica
loads and indexes the same OKF revision.

Rollback is selecting the prior approved revision, mounting or promoting that
revision, and rebuilding the active OKF index:

```bash
python services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
# mount or restore the prior tenant revision, then reload the running service
curl -X POST "$INVESTIGATION_AGENT_URL/v1/admin/okf/reload" \
  -H "X-API-Key: $OKF_ADMIN_API_KEY"
```
