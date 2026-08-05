# Partner enrichment fusion (hybrid device/location)

**Posture:** Tarka does not replace Fingerprint / Incognia. Score 4.0 on device/location means partner signals are first-class in **evaluate → graph writeback hints → case evidence**.

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
