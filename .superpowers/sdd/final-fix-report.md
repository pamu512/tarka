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
