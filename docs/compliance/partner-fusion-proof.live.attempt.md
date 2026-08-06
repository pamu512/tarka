# L2 live partner proof — attempt log

**Machine status file (CI):** [`partner-fusion-proof.live.status`](./partner-fusion-proof.live.status)  
**Format for CI:** `LIVE` or `WAIVED — reason: …` only (see `partner_fusion_live_status_gate.py`).

## 2026-08-06 — Attempted live; BLOCKED

| Check | Result |
| --- | --- |
| `DECISION_API_URL` | unset |
| `FINGERPRINT_REQUEST_ID` / `INCOGNIA_ACCOUNT_ID` | unset |
| `PARTNER_FUSION_PROOF_TENANT` | unset |
| `REQUIRE_LIVE_PARTNER_PROOF=1 --mode fixture` | exit **1** (fail-closed) |
| `REQUIRE_LIVE_PARTNER_PROOF=1 --mode live` | exit **1** (`DECISION_API_URL required`) |
| `partner-fusion-proof.live.sha256` | **not written** (no fake pin) |

**Status file kept:** `WAIVED — reason: no live vendor credentials in OSS CI`

### Operator unblock (when creds exist)

```bash
export DECISION_API_URL=https://… 
export PARTNER_FUSION_PROOF_TENANT=…
export FINGERPRINT_REQUEST_ID=…   # and/or INCOGNIA_ACCOUNT_ID
export REQUIRE_LIVE_PARTNER_PROOF=1
python3 scripts/oss/partner_fusion_tenant_proof.py --mode live \
  --out artifacts/partner-fusion-proof.live.json
# On exit 0 + ok:true + partner_evidence:
#   copy digest → docs/compliance/partner-fusion-proof.live.sha256
#   set partner-fusion-proof.live.status to exactly: LIVE
```

See [partner-fusion-proof-runbook.md](./partner-fusion-proof-runbook.md).
