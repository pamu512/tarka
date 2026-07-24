# Final release-blocker fix report

Status: `DONE_WITH_CONCERNS`

Branch: `ide/category-leader-roadmap-047e`

## Fix commits

- `4064d78b` — `fix(rules): reject malformed rule packs safely`
- `f4bf2ac0` — `fix(decision): preserve idempotent audited outcomes`
- `3b0b291d` — `fix(copilot): harden provenance grounding and run audit`
- `7af085ef` — `fix(deploy): secure lite defaults and probe access`

## Delivered findings

- Fixed Rust invalid-rule ownership and atomic malformed-rule rejection.
- Kept deployed and source decision idempotency/evidence implementations and tests byte-identical.
- Bound evaluate idempotency keys to canonical request fingerprints, with short in-flight leases, owner-checked completion/release, and long-lived completed results.
- Applied `test_bypass` before deployed audit, immutable decision log, downstream publications, and response construction.
- Added complete whitelist/blacklist decision evidence to durable audit and decision-log records.
- Added deterministic OKF source manifests, fail-closed URI/hash validation, validated backlinks, tamper tests, and retained unknown-type tolerance.
- Added durable tenant-scoped AgentRun persistence with SQLite restart/readback and fsynced emergency audit fallback.
- Added textual PII rejection, claim-specific exact grounding, and calculated recall/citation/abstention gates.
- Secured lite-compose defaults, explicitly preserved the insecure quickstart opt-in, exempted only documented probes, and added fraud-stack-lite probes.
- Added the complete source decision-API suite to CI without changing the pinned Ruff or npm-audit commands.
- Preserved rolling-restart multi-replica operation; no reload service was added.

## Fresh verification

Rust toolchain:

```bash
rustc +stable --version
cargo +stable --version
```

Result: `rustc 1.97.1`, `cargo 1.97.1`.

```bash
cargo +stable check --manifest-path services/rule-engine/Cargo.toml
cargo +stable test --manifest-path services/rule-engine/Cargo.toml
cargo +stable check --manifest-path packages/tarka-rule-engine/Cargo.toml
cargo +stable test --manifest-path packages/tarka-rule-engine/Cargo.toml
```

Result: exit 0; service rule engine `4 passed`; package rule engine `5 passed`; doc tests passed.

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result: exit 0; `272 passed, 1 skipped`.

```bash
PYTHONPATH=services/shared:packages/shared-core python3 -m pytest -q \
  services/shared/tests/test_auth.py \
  services/shared/tests/test_auth_rbac_tenant_scopes.py
```

Result: exit 0; `9 passed`.

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// \
REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `49 passed, 1 skipped`.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// \
REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `349 passed, 113 contract tests deselected`.

```bash
python3 services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core \
python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py
python3 infra/scripts/deploy/validate_env_contract.py
```

Result: exit 0; validator accepted the committed shared bundle; `65 passed`; env contract covered `8/8` required keys.

The frozen corpus calculates and enforces:

- recall@10 `>= 0.95`
- exact citation resolution `>= 0.995`
- unsupported-question abstention `>= 0.98`

```bash
python3 -m ruff --version
python3 -m ruff check .
python3 -m ruff format --check services/
```

Result: exit 0; `ruff 0.15.22`; all checks passed; `1182 files already formatted`.

```bash
npm ci
npm audit --audit-level=low
npm run test -w tarka-ui
python3 infra/scripts/ci/check_frontend_mock_mode.py
npm run build -w tarka-ui
```

Result: exit 0; `0 vulnerabilities`; `49` test files and `144` tests passed; mock-mode guard passed; production build completed.

```bash
diff -u \
  services/decision-api/src/decision_api/evaluate_idempotency.py \
  services/legacy_v1_decision_api/src/decision_api/evaluate_idempotency.py
diff -u \
  services/decision-api/src/decision_api/decision_evidence.py \
  services/legacy_v1_decision_api/src/decision_api/decision_evidence.py
diff -u \
  services/decision-api/tests/test_evaluate_idempotency.py \
  services/legacy_v1_decision_api/tests/test_evaluate_idempotency.py
```

Result: exit 0 with no differences.

```bash
git diff --check
git diff --name-only -- docs/superpowers/specs docs/superpowers/plans
git ls-files --others --exclude-standard
```

Result before report creation: exit 0; no whitespace errors; no plan/design changes; only intended new source/test fixtures were untracked and then committed. Test-generated SQLite, JSONL, source decision data/rules, and staging bundles were removed or restored.

## Remaining concerns

- Docker, Docker Compose, and Helm CLIs are not installed on this worker, so live Compose rendering and Helm lint/template commands could not run locally. Static deployment contracts and the environment-contract validator passed; CI retains Helm lint/render coverage.
- Python tests emit one existing Starlette/httpx deprecation warning. Rust package checks emit existing PyO3/dead-code warnings. Neither gate failed.
- The deployed decision suite followed its CI source-of-truth `not contract` marker; 113 external contract tests require their contract environment and were not executed locally.

## Final-review follow-up wave

Status: `DONE_WITH_CONCERNS`

Fix commits:

- `fd127e78` — `fix(decision): harden evaluation lifecycle parity`
- `45ee226c` — `fix(copilot): enforce durable provenance and safe diagnostics`
- `93de5a8b` — `fix(deploy): persist agent runs on single replica`

Delivered:

- Added owner-token CAS renewal/completion/release around evaluate requests, endpoint exception release, lease-loss failure, and source/deployed endpoint regressions.
- Persisted AgentRun SQLite under a named Compose volume and Helm PVC, made local SQLite single-replica, failed chart templates above one replica, documented the external shared-store upgrade, and surfaced review-state update failures.
- Enforced opaque landmark case IDs and recursive PII rejection for email, phone, payment/account/card, SSN/national ID, IP address, street address, and explicit person-name values.
- Replaced concept-derived provenance with independently hashed canonical source snapshots, strict manifests, fail-closed missing/extra/duplicate/tamper handling, and validated backlinks.
- Added complete privacy-masked list-entry identity to whitelist/blacklist evidence hashes, audits, and immutable decision logs.
- Exercised production citation adaptation and exact claim grounding for concept and evidence IDs, with calculated recall, citation-resolution, and unsupported-abstention thresholds.
- Recomputed source and deployed test-bypass inference/challenge outputs before every durable, downstream, and response representation.
- Reduced public health/readiness output to stable codes and moved raw diagnostics behind authenticated admin access.

Fresh verification:

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q tests/test_evaluate_idempotency.py
```

Result: exit 0; `7 passed`.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q tests/test_evaluate_idempotency.py
```

Result: exit 0; `7 passed`.

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `49 passed, 1 skipped`.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `349 passed, 113 contract tests deselected`.

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result: exit 0; `272 passed, 1 skipped`.

```bash
PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core \
python3 -m pytest -q \
  services/investigation-agent/tests/test_agent_run_deployment.py \
  services/investigation-agent/tests/test_agent_run_store.py \
  services/investigation-agent/tests/test_production_readiness.py
```

Result: exit 0; `17 passed`.

```bash
PYTHONPATH=services/shared:packages/shared-core python3 -m pytest -q \
  services/shared/tests/test_auth.py \
  services/shared/tests/test_auth_rbac_tenant_scopes.py
```

Result: exit 0; `9 passed`.

```bash
python3 services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core \
python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py
python3 infra/scripts/deploy/validate_env_contract.py
```

Result: exit 0; shared bundle valid; `65 passed`; environment contract covered `8/8` required keys. The corpus calculated and enforced recall@10 `>=95%`, exact citation resolution `>=99.5%`, and unsupported abstention `>=98%`.

```bash
python3 -m ruff --version
python3 -m ruff check .
python3 -m ruff format --check services/
```

Result: exit 0; `ruff 0.15.22`; all checks passed; `1182 files already formatted`.

```bash
npm ci
npm audit --audit-level=low
npm run test -w tarka-ui
python3 infra/scripts/ci/check_frontend_mock_mode.py
npm run build -w tarka-ui
```

Result: exit 0; `0 vulnerabilities`; `49` files and `144` tests passed; mock-mode guard passed; build completed.

```bash
cargo +stable check --manifest-path services/rule-engine/Cargo.toml
cargo +stable test --manifest-path services/rule-engine/Cargo.toml
cargo +stable check --manifest-path packages/tarka-rule-engine/Cargo.toml
cargo +stable test --manifest-path packages/tarka-rule-engine/Cargo.toml
```

Result: exit 0; rule-engine `4 passed`; tarka-rule-engine `5 passed`; doc tests passed.

```bash
diff -u services/decision-api/src/decision_api/evaluate_idempotency.py \
  services/legacy_v1_decision_api/src/decision_api/evaluate_idempotency.py
diff -u services/decision-api/src/decision_api/decision_evidence.py \
  services/legacy_v1_decision_api/src/decision_api/decision_evidence.py
diff -u services/decision-api/tests/test_evaluate_idempotency.py \
  services/legacy_v1_decision_api/tests/test_evaluate_idempotency.py
git diff --check
git diff --name-only -- docs/superpowers/specs docs/superpowers/plans
```

Result: exit 0; parity files are identical; no whitespace errors; no plan/design files changed. Test-generated SQLite, JSONL, decision data, and runtime bundles were removed or restored before commit.

Follow-up concerns:

- Helm is unavailable on this worker, so the new Helm failure guards were verified by deployment contract tests and template inspection rather than a local `helm template` invocation.
- The configured legacy CI suite excludes 113 Schemathesis contract cases; the complete 349-test non-contract suite passed.
- Existing Starlette/httpx, PyO3, Rust dead-code, and frontend chunk-size warnings remain non-failing.
