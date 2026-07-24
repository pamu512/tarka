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
