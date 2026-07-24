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

## Remaining re-review closure

Status: `DONE_WITH_CONCERNS`

Fix commits:

- `eff1712e` — `fix(decision): fence idempotent audit commits`
- `91f76589` — `fix(copilot): make review and grounding fail closed`
- `38e9826e` — `fix(deploy): prevent sqlite rollout overlap`

Delivered:

- Kept the idempotency heartbeat active through response completion, renewed the
  owner token immediately before each source/deployed audit commit with an
  extended commit lease, released only pre-commit failures, and wrote a
  long-lived blocked outcome after post-commit completion uncertainty.
- Added deterministic races proving ownership loss writes zero audits, delayed
  commits retain one owner/one audit, and completion CAS failure leaves one
  audit while blocking retries.
- Co-located AgentRun and human review rows in one SQLite store and transaction,
  with unique tenant/turn review upsert, rollback on injected failure, and
  idempotent retry metrics.
- Added unlabeled domestic-phone and conservative two-token person-name
  detection while preserving fraud-domain phrases.
- Required claim-specific tool-call indices plus exact selected-hit concept and
  evidence IDs for `search_knowledge`, updated prompt/OpenAPI schemas, and added
  an independent 21-case parser/enforcer/adapter quality fixture.
- Added complete landmark concept + canonical snapshot + manifest export,
  validated by the parser with missing/tampered snapshot regressions.
- Set all local-SQLite Helm Deployments to `Recreate` and corrected the ready
  OpenAPI response contract for `ready`, `degraded`, and sanitized 503 codes.

Fresh verification:

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q tests/test_evaluate_idempotency.py
```

Result: exit 0; `9 passed`.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q tests/test_evaluate_idempotency.py
```

Result: exit 0; `9 passed`.

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `57 passed, 1 skipped`.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `356 passed, 113 contract tests deselected`.

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result: exit 0; `311 passed, 1 skipped`.

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
  services/investigation-agent/tests/test_okf_end_to_end.py \
  services/investigation-agent/tests/test_citation_quality_gate.py \
  services/investigation-agent/tests/test_agent_run_deployment.py \
  services/investigation-agent/tests/test_agent_run_store.py \
  services/investigation-agent/tests/test_production_readiness.py
python3 infra/scripts/deploy/validate_env_contract.py
```

Result: exit 0; shared bundle valid; `114 passed`; environment contract covered
`8/8` required keys. The retrieval corpus enforced recall@10 `>=95%`, exact
citation resolution `>=99.5%`, and unsupported abstention `>=98%`; the
independent adversarial fixture enforced exact concept+evidence precision
`>=99.5%` and unsupported abstention `>=98%` over 20 unsupported cases.

```bash
python3 -m ruff --version
python3 -m ruff check .
python3 -m ruff format --check services/
```

Result: exit 0; `ruff 0.15.22`; all checks passed; `1185 files already formatted`.

```bash
npm ci
npm audit --audit-level=low
npm run test -w tarka-ui
python3 infra/scripts/ci/check_frontend_mock_mode.py
npm run build -w tarka-ui
```

Result: exit 0; `0 vulnerabilities`; `49` files and `144` tests passed;
mock-mode guard passed; build completed.

```bash
cargo +stable check --manifest-path services/rule-engine/Cargo.toml
cargo +stable test --manifest-path services/rule-engine/Cargo.toml
cargo +stable check --manifest-path packages/tarka-rule-engine/Cargo.toml
cargo +stable test --manifest-path packages/tarka-rule-engine/Cargo.toml
```

Result: exit 0; rule-engine `4 passed`; tarka-rule-engine `5 passed`; doc tests
passed.

```bash
diff -u services/decision-api/src/decision_api/evaluate_idempotency.py \
  services/legacy_v1_decision_api/src/decision_api/evaluate_idempotency.py
diff -u services/decision-api/tests/test_evaluate_idempotency.py \
  services/legacy_v1_decision_api/tests/test_evaluate_idempotency.py
git diff --check
git diff --name-only -- docs/superpowers/specs docs/superpowers/plans
git status --porcelain=v2 --untracked-files=all
```

Result: exit 0; idempotency source/deployed files are identical; no whitespace
errors; no plan/design changes; no generated or untracked artifacts remained.

Remaining concerns:

- Helm and Docker CLIs are unavailable on this worker, so `Recreate` was
  verified through all three static deployment contracts and template
  inspection; CI retains live Helm lint/render coverage.
- The configured legacy CI source-of-truth excludes 113 Schemathesis contract
  cases that require their external contract environment.
- Existing Starlette/httpx, PyO3/dead-code, and frontend chunk-size warnings
  remain non-failing.

## Final residual findings closure

Status: `DONE_WITH_CONCERNS`

Fix commits:

- `d309c429` — `fix(decision): upgrade durable sqlite audits on startup`
- `4e67853f` — `fix(copilot): withhold invalid tool-bound narratives`
- `41d3ecd6` — `fix(copilot): preserve atomic review event history`
- `07720fd1` — `fix(okf): fail closed on PII and readiness`

Delivered:

- Added identical source/deployed SQLite normal-start upgrades using
  `PRAGMA table_info/index_list`, additive durable-idempotency columns, and a
  verified unique tenant/key index. Existing audit rows and nullable legacy
  keys remain valid; duplicate non-null tenant/key writes fail.
- Added `tool_call_binding_invalid` to standard/strict narrative withholding
  and expanded the runtime-backed adversarial fixture with omitted and failed
  case, graph, audit, and knowledge call bindings.
- Replaced review upserts with append-only event history. Content-identical
  retries reuse the existing event, distinct reviewer/status/note events
  append, latest lookup is deterministic, and the history store/endpoint
  returns latest-first events. Legacy rows and the pre-history unified table
  upgrade transactionally and idempotently; event append and AgentRun current
  review state remain one transaction.
- Removed the date-like exception for compact NANP-shaped values, including
  `2026072401`; expanded case-insensitive embedded-name bigram scanning; and
  centralized fraud/playbook/generic/function vocabulary to retain safe fraud
  prose.
- Readiness now returns 200 `ready` only when RAG and every other enabled
  knowledge path are healthy. Disabled OKF is allowed; enabled-path failures
  return sanitized 503 `not_ready`. OpenAPI and operator docs match runtime.

Fresh verification:

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `59 passed, 1 skipped`, including the populated legacy-SQLite
normal-start upgrade and durable idempotency tests.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `358 passed, 113 contract tests deselected`, including the
mirrored populated legacy-SQLite normal-start upgrade and durable idempotency
tests.

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result: exit 0; `357 passed, 1 skipped`; review migration/history/rollback,
narrative withholding, PII, and readiness regressions passed.

```bash
python3 services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core \
python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py \
  services/investigation-agent/tests/test_citation_quality_gate.py \
  services/investigation-agent/tests/test_agent_run_deployment.py \
  services/investigation-agent/tests/test_agent_run_store.py \
  services/investigation-agent/tests/test_plugin_and_maker_checker.py \
  services/investigation-agent/tests/test_production_readiness.py \
  services/investigation-agent/tests/test_okf_cli.py
python3 infra/scripts/deploy/validate_env_contract.py
```

Result: exit 0; shared bundle valid; `165 passed`; environment contract covered
`8/8` required keys. Runtime-backed citation precision remained `>=99.5%`,
actual unsupported abstention `>=98%`, and retrieval recall@10 `>=95%`.

```bash
PYTHONPATH=services/shared:packages/shared-core python3 -m pytest -q \
  services/shared/tests/test_auth.py \
  services/shared/tests/test_auth_rbac_tenant_scopes.py
```

Result: exit 0; `9 passed`.

```bash
python3 -m ruff --version
python3 -m ruff check .
python3 -m ruff format --check services/
```

Result: exit 0; `ruff 0.15.22`; all checks passed; `1190 files already
formatted`.

```bash
npm ci
npm audit --audit-level=low
npm run test -w tarka-ui
python3 infra/scripts/ci/check_frontend_mock_mode.py
npm run build -w tarka-ui
```

Result: exit 0; `0 vulnerabilities`; `49` test files and `144` tests passed;
mock-mode guard passed; production build completed.

```bash
cargo +stable check --manifest-path services/rule-engine/Cargo.toml
cargo +stable test --manifest-path services/rule-engine/Cargo.toml
cargo +stable check --manifest-path packages/tarka-rule-engine/Cargo.toml
cargo +stable test --manifest-path packages/tarka-rule-engine/Cargo.toml
```

Result: exit 0; service rule engine `4 passed`; package rule engine `5 passed`;
doc tests passed.

```bash
diff -u services/decision-api/src/decision_api/db.py \
  services/legacy_v1_decision_api/src/decision_api/db.py
diff -u services/decision-api/tests/test_sqlite_startup_migration.py \
  services/legacy_v1_decision_api/tests/test_sqlite_startup_migration.py
git diff --check
git diff --name-only -- docs/superpowers/specs docs/superpowers/plans
git status --porcelain=v2 --untracked-files=all
```

Result before this report commit: source/deployed startup implementations and
tests were identical; no whitespace errors, plan/design edits, generated
databases, decision logs, or other untracked artifacts remained.

Remaining concerns:

- The previously reported broader legacy Schemathesis diagnostic remains
  unresolved at `34 failed, 79 passed, 357 deselected`; it is outside the
  configured source-of-truth release suite but prevents claiming a clean
  all-marker contract run.
- Existing Starlette/httpx, Rust dead-code, npm deprecation, and frontend
  chunk-size warnings remain non-failing.

## Durable final release gate

Status: `DONE_WITH_CONCERNS`

Fix commits:

- `0e11d0a2` — `fix(decision): make evaluate idempotency durable`
- `3bc9c668` — `fix(copilot): recover unified review persistence`
- `10055f4e` — `fix(copilot): bind tool claims and abstain safely`
- `1145db56` — `fix(okf): promote sanitized landmark bundles`

Delivered:

- Added source/deployed audit-model uniqueness on
  `(tenant_id, idempotency_key)`, durable request fingerprints and serialized
  responses, and the deployable decision migration. Redis is admission/cache
  only; unique or ambiguous commits roll back and reconstruct the one committed
  response. Whitelist, blacklist, normal, and test-bypass commits all use the
  durable path.
- Added Redis-loss concurrency, fingerprint mismatch, cache-completion failure,
  and ambiguous-commit regressions in both decision trees.
- Transactionally migrated legacy review rows into the unified AgentRun store
  and rehydrated emergency JSONL runs into SQLite before atomic review updates.
- Added compact domestic-phone and case-insensitive name detection while
  centralizing fraud/playbook vocabulary to preserve safe domain phrases.
- Required successful selected tool-call indices for every tool claim and exact
  selected-hit IDs for knowledge claims. Exact-ID violations now withhold prose
  in standard and strict modes.
- Exposed sanitized landmark concept + canonical snapshot + manifest export in
  the operator CLI, rejected caller-supplied hashes, and documented promotion.
- Clarified readiness semantics for SQLite, RAG, OKF, and degraded responses.

Fresh verification:

```bash
cd services/legacy_v1_decision_api
tmp_db=$(mktemp /tmp/decision-migration-XXXXXX.sqlite3)
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL="sqlite+aiosqlite:///$tmp_db" python3 -m alembic upgrade head
```

Result: exit 0; all 10 revisions applied through `20260724_010`. The deployed
legacy tree is the repository's migration owner and is copied into both
deployable decision images; the source tree has no separate Alembic entrypoint.

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `58 passed, 1 skipped`.

```bash
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; `357 passed, 113 contract tests deselected`.

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result: exit 0; `341 passed, 1 skipped`.

```bash
python3 services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core \
python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py \
  services/investigation-agent/tests/test_citation_quality_gate.py \
  services/investigation-agent/tests/test_agent_run_deployment.py \
  services/investigation-agent/tests/test_agent_run_store.py \
  services/investigation-agent/tests/test_production_readiness.py \
  services/investigation-agent/tests/test_okf_cli.py
python3 infra/scripts/deploy/validate_env_contract.py
```

Result: exit 0; shared bundle valid; `146 passed`; deployment/environment
contract covered `8/8` required keys. The runtime-backed gates enforce
recall@10 `>=95%`, exact concept+evidence citation precision `>=99.5%`, and
actual unsupported abstention `>=98%` over at least 20 adversarial cases.

```bash
PYTHONPATH=services/shared:packages/shared-core python3 -m pytest -q \
  services/shared/tests/test_auth.py \
  services/shared/tests/test_auth_rbac_tenant_scopes.py
```

Result: exit 0; `9 passed`.

```bash
python3 -m ruff --version
python3 -m ruff check .
python3 -m ruff format --check services/
```

Result: exit 0; `ruff 0.15.22`; all checks passed; `1188 files already
formatted`.

```bash
npm ci
npm audit --audit-level=low
npm run test -w tarka-ui
python3 infra/scripts/ci/check_frontend_mock_mode.py
npm run build -w tarka-ui
```

Result: exit 0; `0 vulnerabilities`; `49` test files and `144` tests passed;
mock-mode guard passed; production build completed.

```bash
cargo +stable check --manifest-path services/rule-engine/Cargo.toml
cargo +stable test --manifest-path services/rule-engine/Cargo.toml
cargo +stable check --manifest-path packages/tarka-rule-engine/Cargo.toml
cargo +stable test --manifest-path packages/tarka-rule-engine/Cargo.toml
```

Result: exit 0; service rule engine `4 passed`; package rule engine `5 passed`;
doc tests passed.

Final repository checks:

```bash
git diff --check
git diff --name-only -- docs/superpowers/specs docs/superpowers/plans
git status --porcelain=v2 --untracked-files=all
```

Result before report commit: no whitespace errors, no plan/design changes, and
no generated SQLite, decision-log, rule-pack, or staging-bundle artifacts.

Remaining concerns:

- A diagnostic run of the broader legacy Schemathesis contract marker reported
  `34 failed, 79 passed, 357 deselected` across simulation, lists, consortium,
  calibration, reporting, rule, feature-store, analytics, admin, and evaluate
  endpoints. These failures are outside the configured decision source-of-truth
  suite and include existing schema-fuzz behavior, but they remain unresolved
  and prevent claiming an entirely clean all-marker contract run.
- Existing Starlette/httpx, PyO3/dead-code, and frontend chunk-size warnings
  remain non-failing.

## Final coherence and diagnostic baseline closure

Status: `DONE_WITH_CONCERNS`

Fix commits:

- `83213e96` — `fix(copilot): keep review history coherent`
- `ba8648e8` — `fix(copilot): close grounding and readiness gaps`

Delivered:

- Review retries now deduplicate only against the latest event. An
  approve → reject → approve sequence appends three events, while an immediate
  retry reuses the current event ID; latest lookup, history ordering, metrics,
  and AgentRun review state agree. Legacy migration digests include stable
  legacy row IDs, preserving identical-content rows even with identical
  timestamps.
- Exact-ID/index enforcement and selected-call token grounding now complete
  before narrative withholding. Missing grounding tokens, no successful
  selected payload, invalid bindings, and fabricated or unrelated exact IDs
  withhold unsupported prose in standard and strict modes. Token overlap is
  evaluated only against the claim's selected successful calls.
- Landmark name checks now use a maintained, case-insensitive common-given-name
  lexicon plus explicit person-name labels. A recognized first name fails
  closed even when followed by a fraud-domain token, while unknown prose
  bigrams such as `Unusual behavior detected` remain valid.
- Readiness follows graceful degradation: disabled paths are neutral; one
  failed enabled path with another usable path returns sanitized 200
  `degraded`; 503 `not_ready` is reserved for no usable knowledge path.
  OpenAPI and operator documentation match runtime.

Fresh verification:

```bash
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core python3 -m pytest -q
```

Result: exit 0; `368 passed, 1 skipped`. This includes API-level
approve/reject/approve coherence, identical legacy-row migration, selected-call
token grounding, narrative withholding, name PII, and readiness tests.

```bash
python3 services/investigation-agent/scripts/validate_okf_bundle.py \
  knowledge/shared --scope shared
PYTHONPATH=services/investigation-agent/src:services/shared:packages/shared-core \
python3 -m pytest -q \
  services/investigation-agent/tests/test_okf_parser.py \
  services/investigation-agent/tests/test_okf_registry.py \
  services/investigation-agent/tests/test_okf_exporters.py \
  services/investigation-agent/tests/test_okf_retrieval.py \
  services/investigation-agent/tests/test_okf_end_to_end.py \
  services/investigation-agent/tests/test_citation_quality_gate.py \
  services/investigation-agent/tests/test_agent_run_deployment.py \
  services/investigation-agent/tests/test_agent_run_store.py \
  services/investigation-agent/tests/test_plugin_and_maker_checker.py \
  services/investigation-agent/tests/test_production_readiness.py \
  services/investigation-agent/tests/test_okf_cli.py
python3 infra/scripts/deploy/validate_env_contract.py
```

Result: exit 0; shared bundle valid; `172 passed`; environment contract covered
`8/8` required keys. The runtime-backed citation quality gate includes a
successful-but-unrelated selected-tool adversarial case and still enforces
exact citation precision `>=99.5%`, actual abstention `>=98%`, and recall@10
`>=95%`.

Schemathesis baseline comparison:

```bash
# Current branch diagnostic
cd services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m contract tests/

# Detached pre-finding baseline at 89d002d7, in an isolated worktree
cd /tmp/tarka-contract-baseline/services/legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m contract tests/
```

Result: the current diagnostic reported `34 failed, 79 passed, 358 deselected`;
the `89d002d7` baseline reported `34 failed, 79 passed, 357 deselected`.
Programmatic comparison found identical 34-endpoint failure sets:
`current-only=0`, `baseline-only=0`. The one deselection difference is the new
non-contract SQLite startup test.

The 34 baseline failures classify as:

- 9 existing permissive request-coercion/accepted-negative-data cases.
- 2 Redis-unavailable contract-fixture cases.
- 5 async contract-fixture `MagicMock` mismatches.
- 18 server errors from contract dependencies not provisioned by the fixture.

No branch-caused Schemathesis failure was found, so no decision schema,
implementation, or contract test was weakened or changed for this diagnostic.
The isolated baseline worktree was removed after comparison.

```bash
cd services/decision-api
PYTHONPATH=src:../shared:../core/src:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/

cd ../legacy_v1_decision_api
PYTHONPATH=src:../shared:../../packages/shared-core \
DATABASE_URL=sqlite+aiosqlite:/// REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest -q -m "not contract" tests/
```

Result: exit 0; source `59 passed, 1 skipped`; deployed legacy `358 passed,
113 contract tests deselected`.

```bash
python3 -m ruff --version
python3 -m ruff check .
python3 -m ruff format --check services/
```

Result: exit 0; `ruff 0.15.22`; all checks passed; `1190 files already
formatted`.

```bash
npm ci
npm audit --audit-level=low
npm run test -w tarka-ui
python3 infra/scripts/ci/check_frontend_mock_mode.py
npm run build -w tarka-ui
```

Result: exit 0; `0 vulnerabilities`; `49` test files and `144` tests passed;
mock-mode guard passed; production build completed.

```bash
cargo +stable check --manifest-path services/rule-engine/Cargo.toml
cargo +stable test --manifest-path services/rule-engine/Cargo.toml
cargo +stable check --manifest-path packages/tarka-rule-engine/Cargo.toml
cargo +stable test --manifest-path packages/tarka-rule-engine/Cargo.toml
```

Result: exit 0; service rule engine `4 passed`; package rule engine `5 passed`;
doc tests passed.

```bash
git diff --check
git diff --name-only -- docs/superpowers/specs docs/superpowers/plans
git status --porcelain=v2 --untracked-files=all
```

Result before this report commit: no whitespace errors, no plan/design edits,
and no generated databases, decision logs, rule packs, or untracked artifacts.

Remaining concerns:

- The 34 baseline Schemathesis failures remain unresolved outside this branch's
  changes; their exact failure set and categories are documented above.
- Existing Starlette/httpx, Rust dead-code, npm deprecation, and frontend
  chunk-size warnings remain non-failing.
