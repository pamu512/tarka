# Scripts

Automation, **CI gates**, benchmarks, ETL helpers, and release tooling. Many subtrees have their own README.

## CI and contract validation

| Script | Purpose |
|--------|---------|
| [`ci/validate_openapi_yaml.py`](ci/validate_openapi_yaml.py) | Parse-check every `contracts/openapi/*.yaml` with PyYAML (same step as `.github/workflows/ci.yml` **lint**). Run: `pip install pyyaml && python scripts/ci/validate_openapi_yaml.py` |
| [`ci/check_integration_contract.py`](ci/check_integration_contract.py) | Integration contract checks (see CI / file header). |
| [`ci/full_stack_smoke.py`](ci/full_stack_smoke.py) | Full-stack smoke helper (see CI / file header). |
| [`ci/verify_release_candidate.sh`](ci/verify_release_candidate.sh) | Bash gate for release candidates. |
| [`github/create_roadmap_epic_issues.py`](github/create_roadmap_epic_issues.py) | One-time helper: create umbrella GitHub issues for [`docs/docs/guides/tarka-12-month-roadmap-execution-kit.md`](../docs/docs/guides/tarka-12-month-roadmap-execution-kit.md) (requires `gh` auth; **do not re-run** on the main repo if issues already exist). |

## Policy and typology

- [`policy/validate_rule_packs.py`](policy/validate_rule_packs.py) — JSON rule packs.
- [`policy/validate_typology_dsl.py`](policy/validate_typology_dsl.py) — typology DSL + predicate registry (CI **lint**).

## ML

- [`ml/validate_ml_promotion_policy.py`](ml/validate_ml_promotion_policy.py), [`ml/validate_signal_catalogs.py`](ml/validate_signal_catalogs.py) — promotion policy and signal catalog gates.

## Documented elsewhere

| Area | README |
|------|--------|
| Replay / aggregates | [`replay/README.md`](replay/README.md) |
| Analytics exports | [`analytics/README.md`](analytics/README.md) |
| Benchmarks | [`benchmarks/README.md`](benchmarks/README.md) |
| Chaos | [`chaos/README.md`](chaos/README.md) |
| Calibration | [`calibration/README.md`](calibration/README.md) |
| Consortium adapter | [`consortium_adapter/README.md`](consortium_adapter/README.md) |
| Integration adapter mock | [`integration_adapter_mock/README.md`](integration_adapter_mock/README.md) |
| Release queue | [`release/README.md`](release/README.md) |

## Python dependencies

Optional shared deps: [`requirements.txt`](requirements.txt). Prefer each service’s `pyproject.toml` or the CI image when running tools next to a specific service.

## Contributing

Full CI matrix and local commands: repo root [`CONTRIBUTING.md`](../CONTRIBUTING.md).
