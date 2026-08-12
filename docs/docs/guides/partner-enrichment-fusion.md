# Partner enrichment fusion (hybrid device/location)

**Posture:** Tarka does not replace Fingerprint / Incognia. **Partner enrichment quality** (device fingerprint / location signals as **optional**) means vendor signals are first-class in **evaluate → graph writeback hints → case evidence** when configured — they enrich relatedness and geo fraud signals; they do **not** link loyalty rings by themselves.

## Configure

```bash
export TARKA_VENDOR_FINGERPRINT_API_KEY=...
export TARKA_VENDOR_INCOGNIA_CLIENT_ID=...
export TARKA_VENDOR_INCOGNIA_CLIENT_SECRET=...
```

Plugins register in `decision_api.vendors.bootstrap`.

## Evaluate

Pass identifiers in evaluate `metadata`:

- `fingerprint_request_id` — Fingerprint Server API event id
- `incognia_account_id` — Incognia account / installation id

Pipeline (`partner_fusion.py`):

1. Fetches vendor signals (audited HTTP)
2. Merges `vendor_*` features + `vendor:*` tags
3. Persists `partner_evidence` + `partner_graph_writeback` on the audit snapshot (Device/Place MERGE hints)

## Rule packs

Use tags such as `vendor:fingerprint` / `vendor:incognia:*` in JSON rules. Example pack: `rules/examples/partner_device_location.json` (if present) or any pack matching those tags.

## Scorecards

`GET /api/ingress/v1/integrations/scorecards?tenant_id=...` — fail closed when credentials incomplete.

## Tenant proof (evaluate → audit → case evidence)

Highest-leverage diligence gate. See [partner-fusion-proof-runbook.md](../../compliance/README.md).

```bash
# CI / no keys
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture

# One live tenant (requires vendor keys + request/account ids)
export DECISION_API_URL=...
export FINGERPRINT_REQUEST_ID=...
export INCOGNIA_ACCOUNT_ID=...
export REQUIRE_LIVE_PARTNER_PROOF=1
python3 scripts/oss/partner_fusion_tenant_proof.py --mode live
```

Fixture stable SHA pin: `docs/compliance/partner-fusion-proof.stable.sha256` (CI diffs after `partner_fusion_tenant_proof.py --mode fixture`).
