# Saarthi Pro — upgrade path from OSS investigation-agent

> **Internal / customer success.** Use when moving from **`services/investigation-agent`** (fraud-stack) to a **Saarthi Pro** tagged build. Final runbooks live with the Pro release.

## Preconditions

1. Record **OSS baseline:** git commit or release tag of fraud-stack; `GET /v1/integration` → note **`contract_version`** and **`profile_id`**.
2. Pro release notes list **pinned fraud-stack commit** and **target `contract_version`** (see [distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md)).

## Configuration carry-over

| OSS env / setting | Action |
|-------------------|--------|
| `CASE_API_URL`, `DECISION_API_URL`, `GRAPH_SERVICE_URL` | Copy; re-validate URLs and TLS in Pro environment. |
| `INTEGRATION_PROFILE_ID` / `integration_profile_id` | Preserve or update per [adapter catalog](saarthi-pro-adapter-catalog-and-certification.md). |
| `COPILOT_*` hardening | Copy set; diff against Pro **recommended defaults** in release notes (new flags may exist). |
| `API_KEYS`, `COPILOT_REQUIRE_INVESTIGATION_API_KEY` | Rotate if policy requires; never reuse dev keys in prod. |
| `OPENAI_API_KEY` / BYOK endpoints | Copy; confirm VPC egress and allowlists. |
| Data dirs (`INVESTIGATION_DATA_DIR`, SQLite DB names) | Plan migration or attach volumes; Pro may use different paths—follow Pro install doc. |

## Verification steps

1. **Contract smoke:** `python scripts/ci/check_integration_contract.py --base-url https://<agent>/` (add `--api-key` if required).
2. **Health:** `GET /v1/health` → confirm `integration.contract_version` matches release notes.
3. **Golden profile (optional):** Re-run agreed profiles in UAT (see [certification checklist](saarthi-pro-certification-checklist.md)).
4. **Canary chat:** One analyst thread with replay/labels **disabled** in UAT first if production-sensitive.

## Rollback

Keep previous agent image/config revision until Pro cutover is signed off; document **rollback = redeploy prior artifact + prior env**.

## Related

- [Saarthi Pro standalone distribution layout](saarthi-pro-standalone-distribution-layout.md)
- [Release notes template](saarthi-pro-release-notes-template.md)
