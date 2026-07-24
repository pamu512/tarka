# Task 7 Report: Packaging, CI, Docs, and End-to-End OKF Gates

## Summary

Implemented Task 7 packaging, CI, documentation, and end-to-end OKF gates.

- Added `--shared-root` tenant validation support to `validate_okf_bundle.py`.
- Added an end-to-end OKF test covering exact lookup, link traversal, memo RAG fill, tenant isolation, atomic rollback, embedding keyword fallback, and exact citation references.
- Updated investigation-agent Docker/env config so the image ships only `knowledge/shared` and reads tenant overlays from an operator-mounted root.
- Added OKF validation and parser/registry/exporter/retrieval/e2e gates to the existing investigation-agent CI job.
- Documented staging vs approved promotion, tenant/shared mount locations, retrieval output, readiness, and rollback.

## TDD Evidence

Red command after correcting test fixture setup:

```bash
cd /workspace/services/investigation-agent && python3 -m pytest -q tests/test_okf_end_to_end.py tests/test_okf_cli.py::test_validate_tenant_bundle_accepts_shared_root_for_logical_links
```

Result:

```text
2 failed, 1 passed in 0.23s
```

Expected failures:

- `test_deployment_config_ships_only_shared_bundle_and_mounts_tenants`: Docker/env OKF shipping config was absent.
- `test_validate_tenant_bundle_accepts_shared_root_for_logical_links`: CLI rejected `--shared-root` as an unknown argument.

Focused green command:

```bash
cd /workspace/services/investigation-agent && python3 -m pytest -q tests/test_okf_end_to_end.py tests/test_okf_cli.py::test_validate_tenant_bundle_accepts_shared_root_for_logical_links
```

Result:

```text
3 passed in 0.21s
```

## Final Verification

Investigation-agent full tests:

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result:

```text
253 passed, 1 skipped, 1 warning in 3.26s
```

OKF CI gate:

```bash
cd /workspace && PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py
```

Result:

```text
51 passed in 0.48s
```

Active shared bundle validator:

```bash
cd /workspace/services/investigation-agent && python3 scripts/validate_okf_bundle.py ../../knowledge/shared --scope shared
```

Result: exit 0, no output.

Ruff:

```bash
cd /workspace/services/investigation-agent && python3 -m ruff check src tests scripts && python3 -m ruff format --check src tests scripts
```

Result:

```text
All checks passed!
92 files already formatted
```

Frontend:

```bash
cd /workspace/frontend && npm test -- --run
```

Result:

```text
Test Files  49 passed (49)
Tests       144 passed (144)
```

Diff checks:

```bash
git -C /workspace diff --check
git -C /workspace status --short
git -C /workspace diff --stat master...HEAD
```

Final result: `git diff --check` exited 0. Status contained only source, docs, CI, Docker/env, and the new end-to-end test; no generated bundles/databases were left modified. `git diff --stat master...HEAD` exited 0 and showed the existing long-lived branch diff. The report path is ignored by `.superpowers/sdd/.gitignore`, so it must be force-added when committing.

## Concerns / Notes

- The local shell did not have `pytest` or `ruff` on PATH initially. I installed investigation-agent dev dependencies with `python3 -m pip install -e ".[dev]" sqlalchemy` and installed Ruff with `python3 -m pip install ruff`.
- Latest Ruff (`0.16.0`) reformatted 14 files under the requested `services/investigation-agent/{src,tests,scripts}` scope so the requested format gate passes.
- `npm ci` installed 659 packages and reported existing audit findings: 2 low and 4 high vulnerabilities. I did not change dependencies.
- Investigation-agent tests modify the tracked `services/investigation-agent/var/investigation-agent/copilot_feedback.sqlite3`; I restored it after test runs so no generated database is included.
- Frontend tests pass but emit `npm warn config ignoring workspace config at /workspace/frontend/.npmrc`.

---

## Review Fix: Task 7 Blockers

### Changes

- Startup lifecycle now indexes every active approved shared and tenant OKF bundle before OKF readiness is declared.
- Admin reload now refreshes the derived OKF index after an activated reload; failed validation reloads do not reindex and keep the prior snapshot/index ready.
- `OkfRegistry.active_bundles()` exposes only active parsed bundles, not merged tenant views.
- End-to-end tests now activate through FastAPI startup/admin reload and call the real `search_knowledge` tool with hybrid embeddings, keyword fallback, citations, isolation, and rollback checks.
- Canonical Compose mounts operator tenant overlays at `/var/lib/tarka/knowledge/tenants:ro`.
- Helm fraud-stack values/template now support an explicit existing PVC for tenant overlays and fail rendering when overlays are enabled without a claim.
- Env/docs now state `OKF_ADMIN_API_KEYS` must also be in `API_KEYS` and tenant-scoped via `API_KEY_TENANT_MAP`.
- NPM high advisories were resolved without `--force`: `axios@1.18.1`, `linkify-it@5.0.2`, `js-yaml@4.3.0`, `brace-expansion@1.1.16`, and `brace-expansion@5.0.8`.
- Reverted prior Task-7-only Ruff formatting noise in pre-existing Python files, including removal of the unrelated `dict.fromkeys` change in `okf_registry.py`.

### Red Evidence

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q tests/test_okf_end_to_end.py
```

Initial review-blocker result:

```text
3 failed, 1 warning in 0.82s
```

Expected failures:

- Startup did not invoke OKF indexing.
- Admin reload did not refresh the OKF index.
- Env/deployment config lacked admin key and overlay mounts.

### Final Verification

```bash
cd /workspace && PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py
```

Result:

```text
52 passed, 1 warning in 1.05s
```

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result:

```text
254 passed, 1 skipped, 1 warning in 3.38s
```

```bash
cd /workspace/services/investigation-agent && python3 scripts/validate_okf_bundle.py ../../knowledge/shared --scope shared
```

Result: exit 0, no output.

```bash
cd /workspace/services/investigation-agent && python3 -m ruff check src/investigation_agent/main.py tests/test_okf_end_to_end.py && python3 -m ruff format --check tests/test_okf_end_to_end.py
```

Result:

```text
All checks passed!
1 file already formatted
```

`python3 -m ruff check src/investigation_agent/okf_registry.py` was also run and failed only on the restored pre-existing C420 dict-comprehension lines. I did not reintroduce `dict.fromkeys` because the review explicitly required removing that Task-7-only noise.

```bash
cd /workspace/frontend && npm test -- --run
```

Result:

```text
Test Files  49 passed (49)
Tests       144 passed (144)
```

```bash
cd /workspace && npm audit --audit-level=high
```

Result: exit 0. Remaining advisories are low severity only:

- `dompurify <=3.4.11`: GHSA-c2j3-45gr-mqc4, low, fix requires `npm audit fix --force` and a breaking `monaco-editor@0.53.0` change.
- `jspdf 2.0.0 - 2.5.2`: low via `dompurify`.
- `monaco-editor >=0.54.0-dev-20250909`: low via `dompurify`, fix available only as a breaking downgrade per npm audit.

```bash
cd /workspace && npm ls brace-expansion linkify-it js-yaml axios --all
```

Result:

```text
axios@1.18.1
linkify-it@5.0.2 overridden
js-yaml@4.3.0 overridden
brace-expansion@1.1.16 overridden
brace-expansion@5.0.8 overridden
```

### Deployment Validation

```bash
cd /workspace && docker compose -f infra/deploy/docker-compose.yml config --quiet
```

Result: not available in this environment (`docker: command not found`).

```bash
cd /workspace && helm lint infra/deploy/helm/fraud-stack
```

Result: not available in this environment (`helm: command not found`).

The static end-to-end test validates the Compose mount and Helm PVC/fail-template configuration.

### Concerns / Notes

- `npm audit --audit-level=high` exits 0, but full audit still exits 1 because three low advisories remain; no high or critical advisories remain.
- Docker and Helm CLIs are absent in this environment, so runtime rendering validation could not be executed here.
- The review-required surgical Ruff revert conflicts with latest Ruff C420 on pre-existing `okf_registry.py` comprehensions; I preserved the requested source shape and did not weaken project config.

## Review Fix: Remaining Task 7 Blockers (Atomic Reload / Full Gates)

### Changes

- Refactored OKF registry reload into `prepare_reload()` plus `activate()`.
- Prepared candidate OKF index rows before activation, then replaced all derived OKF SQLite rows in one transaction before activating the candidate.
- Added rollback-safe insert helper; injected mid-index failures now roll back the SQLite transaction and keep the prior registry snapshot/readiness active.
- Added registry/index generation locking across reload activation and retrieval so callers cannot observe mixed generations.
- Added lifecycle/tool tests for:
  - removed concept purge from SQLite;
  - injected mid-index rollback keeping prior searchable results/readiness.
- Fixed C420 and all exact CI Ruff findings; nested service Ruff configs now extend the root repo config instead of unintentionally overriding it.
- Updated all DOMPurify overrides from 3.4.11 to 3.4.12 and refreshed the lock without `--force`.
- Corrected Compose tenant overlay source to `../../knowledge/tenants` and added `knowledge/tenants/README.md`.
- Wired OKF tenant overlay existing-PVC values/fail-closed mounts into `fraud-stack`, `tarka`, and `fraud-stack-lite`.

### Red Evidence

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q tests/test_okf_end_to_end.py
```

Result before the atomic implementation:

```text
2 failed, 3 passed, 1 warning in 0.90s
```

Expected failures:

- `test_admin_reload_purges_removed_okf_concepts`: stale OKF row remained in SQLite.
- `test_mid_index_failure_rolls_back_registry_and_search_index`: injected index failure was not observed and reload returned 200.

### Final Verification

```bash
cd /workspace && python3 -m ruff check . && python3 -m ruff format --check services/
```

Result:

```text
All checks passed!
1193 files already formatted
```

```bash
cd /workspace && python3 services/investigation-agent/scripts/validate_okf_bundle.py knowledge/shared --scope shared && PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core python3 -m pytest -q services/investigation-agent/tests/test_okf_parser.py services/investigation-agent/tests/test_okf_registry.py services/investigation-agent/tests/test_okf_exporters.py services/investigation-agent/tests/test_okf_retrieval.py services/investigation-agent/tests/test_okf_end_to_end.py
```

Result:

```text
54 passed, 1 warning in 1.26s
```

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest --cov=investigation_agent --cov-report=xml --cov-report=term-missing --cov-fail-under=52 -m "not golden_profile" tests/
```

Result:

```text
245 passed, 1 skipped, 11 deselected, 1 warning in 6.48s
Required test coverage of 52% reached. Total coverage: 62.53%
```

```bash
cd /workspace && npm ci && npm run test -w tarka-ui && python3 infra/scripts/ci/check_frontend_mock_mode.py && npm run build -w tarka-ui
```

Result:

```text
found 0 vulnerabilities
Test Files  49 passed (49)
Tests       144 passed (144)
OK: frontend production mock-mode guard passed.
✓ built in 1.18s
```

```bash
cd /workspace && npm audit
```

Result:

```text
found 0 vulnerabilities
```

```bash
cd /workspace && git diff --check
```

Result: exit 0, no output.

### Deployment Validation

```bash
command -v docker || true; docker compose version 2>/dev/null || true
```

Result: exit 0, no output. Docker Compose is not installed in this environment.

```bash
command -v helm || true; helm version --short 2>/dev/null || true
```

Result: exit 0, no output. Helm is not installed in this environment.

Static deployment contract coverage is included in `tests/test_okf_end_to_end.py` for Compose plus all supported investigation-agent Helm charts.

### Concerns / Notes

- Exact CI Ruff required `ruff format services/`, which reformatted 200 service files; this was necessary to make the full-scope CI format gate pass without ignores or scope narrowing.
- Docker and Helm CLIs are absent in this environment, so live compose config and Helm rendering could not be executed here.

## Review Fix: Final Task 7 Blockers (Surgical Churn Revert / Async Gate)

### Changes

- Reverted the broad churn from `93a2c86c` outside the intended Task 7 surface:
  removed nested Ruff `extend` additions, restored `tarka-verifier` files,
  restored unrelated ContextVar/SIM115/C420 edits outside OKF, and removed the
  full-service formatting sweep from the effective `d72f01d7..HEAD` diff.
- Replaced the registry `threading.RLock` generation guard with an app-level
  shared `asyncio.Lock` used by startup load/index/activation, admin reload, and
  async OKF retrieval/tool dispatch.
- Added deterministic async concurrency coverage for:
  - retrieval suspended in RAG while a reload waits on the generation gate;
  - concurrent reload candidates serialized from preparation through activation,
    leaving the later active tenant data visible.
- Added CI enforcement for `npm audit --audit-level=low` in the existing
  frontend job.
- Expanded existing Helm CI to lint/render all supported charts:
  `fraud-stack`, `tarka`, and `fraud-stack-lite`.
- Documented that admin reload is process-local and that multi-replica
  Kubernetes promotion requires a rolling restart or equivalent per-replica
  orchestration after approved bundle/PVC updates.

### Final Verification

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q tests/test_okf_end_to_end.py::test_async_retrieval_holds_generation_gate_until_rag_completes tests/test_okf_end_to_end.py::test_concurrent_reloads_serialize_candidate_preparation_through_activation
```

Result:

```text
2 passed, 1 warning in 0.79s
```

```bash
cd /workspace && python3 services/investigation-agent/scripts/validate_okf_bundle.py knowledge/shared --scope shared && PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core python3 -m pytest -q services/investigation-agent/tests/test_okf_parser.py services/investigation-agent/tests/test_okf_registry.py services/investigation-agent/tests/test_okf_exporters.py services/investigation-agent/tests/test_okf_retrieval.py services/investigation-agent/tests/test_okf_end_to_end.py
```

Result:

```text
56 passed, 1 warning in 1.23s
```

```bash
cd /workspace/services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest --cov=investigation_agent --cov-report=xml --cov-report=term-missing --cov-fail-under=52 -m "not golden_profile" tests/
```

Result:

```text
247 passed, 1 skipped, 11 deselected, 1 warning in 6.81s
Required test coverage of 52% reached. Total coverage: 62.58%
```

```bash
cd /workspace && npm ci && npm audit --audit-level=low && npm run test -w tarka-ui && python3 infra/scripts/ci/check_frontend_mock_mode.py && npm run build -w tarka-ui
```

Result:

```text
found 0 vulnerabilities
found 0 vulnerabilities
Test Files  49 passed (49)
Tests       144 passed (144)
OK: frontend production mock-mode guard passed.
✓ built in 1.29s
```

```bash
cd /workspace && npm audit --audit-level=low
```

Result:

```text
found 0 vulnerabilities
```

```bash
cd /workspace && python3 -m ruff check .; ruff_check_status=$?; python3 -m ruff format --check services/; ruff_format_status=$?; echo ruff_check_status=$ruff_check_status; echo ruff_format_status=$ruff_format_status; exit 0
```

Result:

```text
ruff_check_status=1
ruff_format_status=1
```

The exact full Ruff gates still fail after removing the prior config inheritance
changes. The failures are pre-existing, unrelated nested-service Ruff findings
(`services/core_v2`, `services/decision-api`, `services/legacy_v1_decision_api`,
`services/tarka-verifier`, and unchanged OKF helper tests). I did not re-add
config inheritance or mass-format/fix unrelated files because that would
reintroduce the broad churn explicitly requested for reversion. Changed Task 7
Python files pass:

```bash
cd /workspace && python3 -m ruff check services/investigation-agent/src/investigation_agent/knowledge_db.py services/investigation-agent/src/investigation_agent/knowledge_store.py services/investigation-agent/src/investigation_agent/main.py services/investigation-agent/src/investigation_agent/okf_registry.py services/investigation-agent/src/investigation_agent/okf_retrieval.py services/investigation-agent/src/investigation_agent/tools.py services/investigation-agent/tests/test_agent_security.py services/investigation-agent/tests/test_okf_end_to_end.py
cd /workspace && python3 -m ruff format --check services/investigation-agent/src/investigation_agent/knowledge_db.py services/investigation-agent/src/investigation_agent/knowledge_store.py services/investigation-agent/src/investigation_agent/main.py services/investigation-agent/src/investigation_agent/okf_registry.py services/investigation-agent/src/investigation_agent/okf_retrieval.py services/investigation-agent/src/investigation_agent/tools.py services/investigation-agent/tests/test_agent_security.py services/investigation-agent/tests/test_okf_end_to_end.py
```

Result:

```text
All checks passed!
8 files already formatted
```

```bash
command -v docker || true; docker compose version 2>/dev/null || true
command -v helm || true; helm version --short 2>/dev/null || true
```

Result: exit 0, no output. Docker Compose and Helm are not installed locally;
static deployment contract coverage is included in
`tests/test_okf_end_to_end.py`, and CI now installs Helm for lint/render gates.

```bash
cd /workspace && git diff --check
```

Result: exit 0, no output.

### Final Concerns / Notes

- Exact full-scope Ruff remains red on unrelated pre-existing nested-service
  findings once the broad config-inheritance workaround is removed.
- Docker Compose and Helm CLIs are absent in this environment; live deployment
  rendering could not be executed locally.

## Review Fix: Ruff Reproducibility Pin

### Changes

- Updated `.github/workflows/ci.yml` to install `ruff==0.15.22` in the existing
  Ruff audit job, matching repository reference commit `59318f85` and CI run
  `30059764068`.
- Installed Ruff 0.15.22 locally and ran the exact CI commands.
- To make the exact pinned gates pass on this branch, applied only the changes
  reported by Ruff 0.15.22 itself:
  - removed two unused `hashlib` imports reported by `ruff check .`;
  - formatted the 18 files reported by `ruff format --check services/`.

### Verification

```bash
cd /workspace && python3 -m pip install --user ruff==0.15.22 && python3 -m ruff --version
```

Result:

```text
Successfully installed ruff-0.15.22
ruff 0.15.22
```

```bash
cd /workspace && PATH="$HOME/.local/bin:$PATH" ruff --version && PATH="$HOME/.local/bin:$PATH" ruff check . && PATH="$HOME/.local/bin:$PATH" ruff format --check services/
```

Result:

```text
ruff 0.15.22
All checks passed!
1177 files already formatted
```

```bash
cd /workspace && git diff --check
```

Result: exit 0, no output.

### Diff Note

The prior Task 7 functional diff remains unchanged. The additional working-tree
delta for this review fix is the CI pin plus the exact source/format changes
required by Ruff 0.15.22 to make the pinned full-repo gates pass.
