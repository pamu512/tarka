# GitLab-shaped product P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. User said `go` — implement in this session.

**Goal:** Introduce `desk_provision.json` and `make product` without changing `make demo`.

**Architecture:** Shared loader reads an optional JSON file; nonempty env wins. Helm and product compose mount the example. Leftover helpers and FLAG mint call the loader.

**Tech Stack:** Python 3 stdlib JSON, pytest, Docker Compose, Helm ConfigMap.

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty plane URL = that plane off.
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`.
- Demo ≠ product. `make demo` unchanged.
- `brochure` env token stays; docs say sales-only overlay.
- No Tarka OSS / third-party desk names in new copy.
- No P-enf1 webhooks / notify.

---

### Task 1: Loader (TDD)

**Files:**
- Create: `services/shared/tests/test_desk_provision.py`
- Create: `services/shared/desk_provision.py`

- [ ] Failing tests first, then loader.

Run: `PYTHONPATH=services/shared python3 -m pytest services/shared/tests/test_desk_provision.py -q`

### Task 2: Schema + leftover wiring

**Files:**
- Create: `infra/deploy/desk_provision.schema.json`
- Create: `infra/deploy/desk_provision.example.json`
- Modify: `services/case-api/src/case_api/leftover.py` leftover flag helpers
- Modify: `services/decision-api/src/decision_api/config.py` `flag_mints_leftover`

### Task 3: Helm + product compose + docs

**Files:**
- Create: `infra/deploy/helm/fraud-stack/templates/desk-provision.yaml`
- Modify: `infra/deploy/helm/fraud-stack/templates/core-api.yaml` (volume + env)
- Modify: `infra/deploy/helm/fraud-stack/values.yaml`
- Create: `infra/deploy/docker-compose.product.yml`
- Create: `scripts/oss/up_product.sh`
- Modify: `Makefile`
- Modify: `README.md`, `docs/docs/guides/clone-demo.md`

### Task 4: Verify + PR

- Loader tests, leftover helper tests, helm string tests, walk_receipts CI.
- Commit, push `honesty/gitlab-shaped-product-p0`, PR into `#384`.
