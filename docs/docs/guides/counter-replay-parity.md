# Counter replay and online/offline parity (v1.2.0)

**Release target:** `v1.2.0` on **2026-05-30**. **Ship hold:** no tag or GitHub release until **[Epic C Release Candidate Gate Criteria](#epic-c-release-candidate-gate-criteria)** are satisfied on the RC commit ([`RELEASE_SCHEDULE.md`](../honesty.md)).

**Scope for May 2026:** Epic C is **frozen for feature work**. Remaining work is **operational validation only**—execute the gate checklist on the RC branch, attach evidence, and obtain sign-offs. Implementation surface (manifest, replay APIs, scripts, CI workflows) is already on trunk; do not expand counter semantics before the tag.

**References:** [redis-agg-key-version-migration.md](./redis-agg-key-version-migration.md) · [roadmap-30-60-90.md](./backtest-before-promote.md) Day 60 · [v1.2.0 release note](../releases/README.md)

---

## Implemented surface (no new features for v1.2.0)

| Area | Location |
|------|----------|
| Counter manifest v1 | [`counter_manifest_v1.json`](../../../services/decision-api/src/decision_api/data/counter_manifest_v1.json), `GET /v1/internal/counters/manifest` |
| Redis key versioning | `AGG_KEY_VERSION` in [`fraud_aggregates.py`](../../../services/shared/fraud_aggregates.py) |
| Offline replay | [`scripts/replay/replay_aggregates.py`](../../../scripts/replay/replay_aggregates.py), [`export_audit_to_jsonl.py`](../../../scripts/replay/export_audit_to_jsonl.py), [`diff_aggregate_redis.py`](../../../scripts/replay/diff_aggregate_redis.py) |
| Ops replay API | `POST /v1/internal/counters/replay`, `POST /v1/internal/counters/replay/from-audit` (token: `COUNTER_REPLAY_TOKEN`) |
| CI / unit parity | [`.github/workflows/counter-parity-smoke.yml`](../../../.github/workflows/counter-parity-smoke.yml), [`test_golden_counters.py`](../../../services/decision-api/tests/test_golden_counters.py), [`test_day60_velocity_windows.py`](../../../services/decision-api/tests/test_day60_velocity_windows.py), [`test_velocity_day60_parity.py`](../../../services/feature-service/tests/test_velocity_day60_parity.py) |
| Feature-service Redis read path | `POST /v1/snapshot`, `POST /v1/velocity/query` when `FEATURE_SERVICE_REDIS_URL` / shared Redis is set |
| Compose defaults | `AGG_KEY_VERSION` on `core-api` and `signal-api` in [`infra/deploy/docker-compose.yml`](../../../infra/deploy/docker-compose.yml) and [`infra/deploy/docker-compose.lite.yml`](../../../infra/deploy/docker-compose.lite.yml) |
| Rule author keys | [velocity-counter-rule-keys.md](./examples/velocity-counter-rule-keys.md) |

---

## Epic C Release Candidate Gate Criteria

**RC definition:** Git commit SHA nominated for `v1.2.0` (release branch or `master` at freeze). Record the SHA in every evidence artifact.

**Evidence bundle:** Attach outputs to the GitHub Release draft, release PR, or `docs/docs/releases/evidence/v1.2.0-epic-c/` (one file per gate is fine). **Gates C-2, C-3a, C-3b, and C-3c are release blockers** until signed off.

### C-1 — RC identity and manifest contract

| Field | Value |
|-------|--------|
| **Verification command** | `git rev-parse HEAD` on the RC checkout; then `curl -sS -H "X-Tarka-Counter-Replay-Token: $COUNTER_REPLAY_TOKEN" http://<decision-api-host>/v1/internal/counters/manifest \| jq .` (or equivalent via core-api `/decisions` prefix). |
| **Expected evidence** | Text file listing **RC SHA**, manifest `version`, and `redis_key_version` matching the RC deploy env (`AGG_KEY_VERSION` or explicit `default`). Screenshot or JSON attachment. CI job [`test_counter_manifest.py`](../../../services/decision-api/tests/test_counter_manifest.py) green on the same SHA. |
| **Sign-off owner** | **Release Manager** |

---

### C-2 — Redis key versioning (staging cutover) — **BLOCKER**

Production-style cutover evidence is **mandatory**. The release **must not** ship without this log.

| Field | Value |
|-------|--------|
| **Verification command** | On a **staging or production-like** profile (not laptop-only): execute the full playbook in **[redis-agg-key-version-migration.md](./redis-agg-key-version-migration.md)**—choose strategy **A**, **B**, or **C**, set `AGG_KEY_VERSION` consistently on decision writers, replay jobs, and feature-service readers, then complete the playbook § *Verification checklist* (manifest, spot `ZCARD`, velocity query spot-check). Capture **complete terminal/session log** (commands + stdout/stderr, no secrets). |
| **Expected evidence** | **Attached log output** showing: (1) chosen migration strategy and `AGG_KEY_VERSION` value, (2) `GET /v1/internal/counters/manifest` with matching `redis_key_version`, (3) at least one successful post-cutover aggregate spot-check, (4) dated environment name (e.g. `staging`, `prod-dr`). Redact credentials; keep key patterns and exit codes. |
| **Sign-off owner** | **Platform / SRE** (executes migration) + **Release Manager** (accepts evidence) |

---

### C-3a — Parity proof: manual weekly runbook on RC — **BLOCKER**

| Field | Value |
|-------|--------|
| **Verification command** | On RC checkout, with local or tunneled Redis and `pip install redis`: run § *Weekly parity runbook* below with `AGG_KEY_VERSION` set to the **same value as RC staging** (e.g. `rc_parity_v1`). |
| **Expected evidence** | Terminal log showing: (1) `replay_aggregates.py` → DB/index **14** exit 0, (2) same fixture → DB/index **15** exit 0, (3) `diff_aggregate_redis.py` exit **0** with no diff output. Include RC SHA and `AGG_KEY_VERSION` in the log header. |
| **Sign-off owner** | **Data Engineering** |

#### Weekly parity runbook (5 minutes)

1. `export AGG_KEY_VERSION=<match-rc-deploy>`
2. `python scripts/replay/replay_aggregates.py --input scripts/replay/fixtures/parity_smoke.jsonl --redis-url redis://127.0.0.1:6379/14`
3. `python scripts/replay/replay_aggregates.py --input scripts/replay/fixtures/parity_smoke.jsonl --redis-url redis://127.0.0.1:6379/15`
4. `python scripts/replay/diff_aggregate_redis.py --left-url redis://127.0.0.1:6379/14 --right-url redis://127.0.0.1:6379/15 --pattern 'fraud:agg*'`

---

### C-3b — Parity proof: `counter-parity-smoke` workflow on RC — **BLOCKER**

| Field | Value |
|-------|--------|
| **Verification command** | From GitHub Actions: **Actions → Counter parity smoke → Run workflow**, select branch/tag at **RC SHA** (or push RC to branch and let weekly schedule run). Alternatively reproduce the job locally: same steps as [`.github/workflows/counter-parity-smoke.yml`](../../../.github/workflows/counter-parity-smoke.yml) with `AGG_KEY_VERSION=ci_parity_v1` (or RC value if validating production key shape). |
| **Expected evidence** | **Workflow run URL** (or local log) showing job **replay-and-diff** succeeded on the RC commit; include commit SHA in run summary. Archive the “Diff aggregate ZSETs” step log (exit 0). |
| **Sign-off owner** | **Release Manager** |

---

### C-3c — Parity proof: `test_golden_counters.py` on RC — **BLOCKER**

| Field | Value |
|-------|--------|
| **Verification command** | `cd services/decision-api && pytest tests/test_golden_counters.py -v --tb=short` (optionally with coverage gate from CI). Run on the **RC commit** in the same Python version as CI (3.12). |
| **Expected evidence** | Pytest log: **all tests passed**, including `TestGoldenEventCounts10xStress` if present. Paste into evidence bundle or link CI `decision-api` job on RC SHA. |
| **Sign-off owner** | **Data Engineering** |

---

### C-4 — Feature-service contract (Day 60): deterministic 5m / 1h / 24h — **BLOCKER**

Day 60 acceptance is **limited** to proving **deterministic** `event_count_5m`, `event_count_1h`, and `event_count_24h` from feature-service when Redis is **shared** with decision-api. No new counter types for v1.2.0.

| Field | Value |
|-------|--------|
| **Verification command** | (1) Start stack with shared Redis and matching `AGG_KEY_VERSION` on `core-api` + `signal-api` (see compose files). (2) Record a fixed event sequence via evaluate (or `AggregateStore` in test). (3) `POST /v1/velocity/query` (feature-service or signal-api `/features` route) with same `tenant_id`, `entity_id`, and payload fields used for aggregates. (4) Assert `velocity_counters.event_count_5m`, `event_count_1h`, `event_count_24h` equal decision-api feature snapshot / evaluate features. **Automated path:** `pytest services/decision-api/tests/test_golden_counters.py services/feature-service/tests/test_shared_velocity.py -q` on RC; plus compose smoke: evaluate then velocity query for one entity. |
| **Expected evidence** | Table or JSON diff showing **exact match** for 5m/1h/24h on at least one tenant/entity after a known event sequence; RC SHA; `AGG_KEY_VERSION` and Redis URL noted. |
| **Sign-off owner** | **Data Engineering** |

---

### C-5 — Compose defaults and rule-pack key documentation

| Field | Value |
|-------|--------|
| **Verification command** | Confirm `infra/deploy/docker-compose.yml` and `infra/deploy/docker-compose.lite.yml` set `AGG_KEY_VERSION: ${AGG_KEY_VERSION:-local_v1}` on **core-api** and **signal-api**. Review [velocity-counter-rule-keys.md](./examples/velocity-counter-rule-keys.md) and confirm rule examples cite `event_count_5m`, `event_count_1h`, `event_count_24h`, and `distinct_session_id_24h` (when `session_id` is present) with **no invented key names**. |
| **Expected evidence** | PR link or diff hunk showing compose env; rule doc merged on RC branch; Release Manager checklist tick. |
| **Sign-off owner** | **Platform Engineering** |

---

### C-6 — Ops replay API smoke (non-blocker if C-3 passes)

| Field | Value |
|-------|--------|
| **Verification command** | With `COUNTER_REPLAY_TOKEN` set on RC deploy: `POST /v1/internal/counters/replay` with a minimal JSON event list; optional `POST .../replay/from-audit` for one known `tenant_id` + `entity_id`. |
| **Expected evidence** | HTTP 200 response log; no 401/503; scratch Redis URL documented. |
| **Sign-off owner** | **Platform / SRE** |

---

## Gate summary

| Gate | Blocker? | Owner |
|------|----------|--------|
| C-1 RC + manifest | Yes | Release Manager |
| C-2 Staging `AGG_KEY_VERSION` cutover log | **Yes** | Platform/SRE + Release Manager |
| C-3a Manual parity runbook | **Yes** | Data Engineering |
| C-3b `counter-parity-smoke` on RC | **Yes** | Release Manager |
| C-3c `test_golden_counters.py` on RC | **Yes** | Data Engineering |
| C-4 Feature-service 5m/1h/24h deterministic | **Yes** | Data Engineering |
| C-5 Compose + rule key docs | Yes | Platform Engineering |
| C-6 Ops replay API smoke | No (recommended) | Platform/SRE |

**All blocker gates (C-2, C-3a–c, C-4, C-5) must be signed before `v1.2.0` tag.**

---

## Audit → JSONL → scratch Redis (reference)

1. `python scripts/replay/export_audit_to_jsonl.py --tenant-id YOUR_TENANT --entity-id YOUR_ENTITY --out /tmp/audit.jsonl --limit 5000`
2. `AGG_KEY_VERSION=<match-rc> python scripts/replay/replay_aggregates.py --input /tmp/audit.jsonl --redis-url redis://localhost:6379/15`
3. `python scripts/replay/diff_aggregate_redis.py --left-url redis://prod:6379/0 --right-url redis://localhost:6379/15 --pattern 'fraud:agg*'`

---

## Related

- [redis-agg-key-version-migration.md](./redis-agg-key-version-migration.md)
- [scripts/replay/README.md](../../../scripts/replay/README.md)
- [v1.2.0-2026-05-30.md](../releases/README.md)
