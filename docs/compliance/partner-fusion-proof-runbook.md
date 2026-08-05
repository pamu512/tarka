# Partner fusion tenant proof (highest-leverage hybrid gate)

**Goal:** Prove Fingerprint / Incognia signals are first-class on **evaluate → audit snapshot → case evidence**, with a content SHA for diligence.

| Tier | Mode | Pin file | Claim |
|------|------|----------|-------|
| **L1 (CI)** | `fixture` | `partner-fusion-proof.stable.sha256` | Hybrid mapping regression |
| **L2 (diligence)** | `live` + named tenant | `partner-fusion-proof.live.sha256` | Real vendor fetch on a customer tenant |

Fixture pin alone does **not** satisfy L2. Sim/fixture SHA ≠ live network proof.

## Fixture mode (CI / no vendor keys)

```bash
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture
# → artifacts/partner-fusion-proof.json
# → artifacts/partner-fusion-proof.sha256
```

Uses `scripts/oss/fixtures/partner_fusion_signals.json`. Exit 0 only when `partner_evidence` + graph writeback vertices/edges are present.

CI verifies the fixture digest matches the committed pin:

```bash
diff -u docs/compliance/partner-fusion-proof.stable.sha256 \
  artifacts/partner-fusion-proof.sha256
```

**Pinned fixture digest (CI):** `docs/compliance/partner-fusion-proof.stable.sha256`  
Current value: `3d1ab910a52dbad2c5ecddcf46b653fbe57966cc9fd5461a1cdc100676a30b88`

## Live mode (named tenant — L2)

Run once per environment/tenant when vendor keys and real request/account ids are available.

### Prerequisites

1. Decision API deployed with Fingerprint and/or Incognia adapters registered.
2. Vendor API keys configured on the decision-api service.
3. A **real** `fingerprint_request_id` (server API event) and/or `incognia_account_id` for the named tenant.
4. Tenant id agreed with customer / deal room (not the default `proof-tenant` for production diligence).

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DECISION_API_URL` | yes | Base URL (e.g. `https://decision.customer.example`) |
| `FINGERPRINT_REQUEST_ID` | one of fp/inc | Server-side Fingerprint event id |
| `INCOGNIA_ACCOUNT_ID` | one of fp/inc | Incognia account or installation id |
| `PARTNER_FUSION_PROOF_TENANT` | yes (named) | Customer tenant id for the proof run |
| `REQUIRE_LIVE_PARTNER_PROOF` | yes | Set to `1` — fail-closed if live path or evidence missing |
| `TARKA_VENDOR_FINGERPRINT_API_KEY` | if using FP | On decision-api host |
| `TARKA_VENDOR_INCOGNIA_CLIENT_ID` | if using Incognia | On decision-api host |
| `TARKA_VENDOR_INCOGNIA_CLIENT_SECRET` | if using Incognia | On decision-api host |
| `PARTNER_FUSION_PROOF_OUT` | optional | Output JSON path (default `artifacts/partner-fusion-proof.json`) |

### Run

```bash
export DECISION_API_URL=https://decision.example
export PARTNER_FUSION_PROOF_TENANT=<customer-tenant-id>
export FINGERPRINT_REQUEST_ID=<server-api-event-id>
export INCOGNIA_ACCOUNT_ID=<account-or-installation-id>
export REQUIRE_LIVE_PARTNER_PROOF=1

python3 scripts/oss/partner_fusion_tenant_proof.py --mode live
```

Exit **0** only when `mode=live` and `audit_snapshot.partner_evidence` is non-empty.  
With `REQUIRE_LIVE_PARTNER_PROOF=1`, fixture fallback or empty evidence exits **1** (fail-closed).

### Pin live SHA (after first successful run)

1. Confirm stdout shows `"ok": true` and `"mode": "live"`.
2. Copy the sidecar digest to the committed L2 pin:

```bash
cp artifacts/partner-fusion-proof.sha256 \
  docs/compliance/partner-fusion-proof.live.sha256
```

3. Archive the proof JSON (deal room or `docs/compliance/` per artifacts policy):

```bash
cp artifacts/partner-fusion-proof.json \
  docs/compliance/partner-fusion-proof.live.json
```

4. Commit both pin and JSON in the same change as the live run evidence:

```bash
git add docs/compliance/partner-fusion-proof.live.sha256 \
        docs/compliance/partner-fusion-proof.live.json
git commit -m "docs: pin live partner fusion proof for <tenant>"
```

5. Record tenant id, trace_id, and run date in the deal room checklist.

**Do not** copy fixture SHA into `partner-fusion-proof.live.sha256`. L1 and L2 pins are separate.

## What “pass” means

| Field | Required |
|-------|----------|
| `audit_snapshot.partner_evidence` | non-empty |
| `audit_snapshot.partner_graph_writeback.vertices` | Device and/or Place (live may vary) |
| `case_evidence.decision_audit.payload_snapshot.partner_evidence` | same rows |
| `stable_sha256` / `content_sha256` | present |
| `mode` | `live` for L2 |

## Release / deal-room checklist

| Bar | Requirement |
|-----|-------------|
| **CI / OSS release (L1)** | Fixture mode green; `partner-fusion-proof.stable.sha256` matches artifact |
| **Customer diligence / L2 hybrid claim** | Live mode green; `partner-fusion-proof.live.sha256` committed **or** explicit waiver: `Partner live proof: WAIVED — reason: …` |
| **PR touching fusion** | Checkbox in `.github/pull_request_template.md` |

## Related

- [partner-enrichment-fusion.md](../docs/guides/partner-enrichment-fusion.md)
- Wave 6 design: `docs/superpowers/specs/2026-08-05-maturity-wave6-design.md`
- Critical 4.5 plan: `docs/superpowers/plans/2026-08-05-critical-4-5-parallel-tracks.md`
- Ops QA desk e2e (scheduled): `.github/workflows/ops-qa-desk-e2e.yml`
