# Partner fusion tenant proof (highest-leverage hybrid gate)

**Goal:** Prove Fingerprint / Incognia signals are first-class on **evaluate → audit snapshot → case evidence**, with a content SHA for diligence.

## Fixture mode (CI / no vendor keys)

```bash
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture
# → artifacts/partner-fusion-proof.json
# → artifacts/partner-fusion-proof.sha256
```

Uses `scripts/oss/fixtures/partner_fusion_signals.json`. Exit 0 only when `partner_evidence` + graph writeback vertices/edges are present.

## Live mode (one real tenant)

```bash
export DECISION_API_URL=https://decision.example
export TARKA_VENDOR_FINGERPRINT_API_KEY=...
export TARKA_VENDOR_INCOGNIA_CLIENT_ID=...
export TARKA_VENDOR_INCOGNIA_CLIENT_SECRET=...
export FINGERPRINT_REQUEST_ID=<server-api-event-id>
export INCOGNIA_ACCOUNT_ID=<account-or-installation-id>
export PARTNER_FUSION_PROOF_TENANT=<tenant>
export REQUIRE_LIVE_PARTNER_PROOF=1

python3 scripts/oss/partner_fusion_tenant_proof.py --mode live
```

Archive `artifacts/partner-fusion-proof.json` + `.sha256` next to the deal room pack.

**Pinned fixture digest (CI):** `docs/compliance/partner-fusion-proof.stable.sha256`  
Current value: `3d1ab910a52dbad2c5ecddcf46b653fbe57966cc9fd5461a1cdc100676a30b88`

## What “pass” means

| Field | Required |
|-------|----------|
| `audit_snapshot.partner_evidence` | non-empty |
| `audit_snapshot.partner_graph_writeback.vertices` | Device and/or Place |
| `case_evidence.decision_audit.payload_snapshot.partner_evidence` | same rows |
| `stable_sha256` / `content_sha256` | present |

## Related

- [partner-enrichment-fusion.md](../docs/guides/partner-enrichment-fusion.md)
- Wave 6 design: `docs/superpowers/specs/2026-08-05-maturity-wave6-design.md`
