# Proof-grade decisioning (P1)

Every fraud vendor sells you their verdict. Tarka sells you the evidence: any
decision, at any time, provable end-to-end by a third party with zero trust in
Tarka.

## The chain

1. **Decision receipt.** Every evaluate returns a receipt with the fired pack,
   score composition, tags, and trace id. Rust evaluates; deterministic,
   replayable.
2. **Signed evidence bundle.** `GET /v1/compliance/evidence` (case-api)
   exports an audit bundle sealed with canonical-JSON SHA-256 bundle hash, a
   sequential per-record hash chain, and an HMAC-SHA256 signature with
   key-id rotation (`evidence/keys` endpoint reports the active key).
3. **Bitemporal graph provenance.** Graph entities and links carry
   ingested_at/observed_at dual clocks; `as_of` reads answer "what did we
   know at time T" (graph-service temporal filter).
4. **Tamper-evident replay.** `tarka replay` / `tarka batch-replay`
   re-evaluate historical decisions from the ClickHouse evidence manifests
   under a deterministic clock, with 100% parity gates. A tampered history
   cannot reproduce the same manifests.
5. **Buyer-verifiable export.** `tarka.training_row/v1` export joins
   receipts with labels — the buyer's own training/audit artifact.

## The auditor path: `tarka verify`

```bash
# export the bundle once (any tenant):
curl -H "x-api-key: ..." "$CASE_API/v1/compliance/evidence?tenant_id=acme" > bundle.json

# verify offline — no Tarka services, no network:
tarka verify --bundle bundle.json --key "$EVIDENCE_SIGNING_SECRET"
#   bundle hash : OK
#   hash chain  : OK (N records)
#   signature   : OK
#   key id      : OK (2b2722402a5f)
#   VERIFIED
```

Without the key (`--bundle` only), hash + chain still prove the bundle's
internal integrity — a third-party auditor who is NOT given the signing key
can confirm the export has not been edited since signing only fails on
signature, never silently.

## Chain-completeness metric

`GET /decisions/v1/loop-metrics?tenant_id=...` now includes
`evidence_chain_completeness`: `{complete, total, ratio}` over the receipt
window — the share of decisions whose chain is complete (receipt + bound
label). `ratio: null` means unknown (no receipts in window), never
0.0 theater. Bake-off rules apply (null = unknown).

## Why vendors cannot follow

SaaS fraud platforms hold the keys and the database: their "audit trail" is
their own infrastructure testifying about itself. Consortium members legally
cannot contribute raw network data into a buyer-visible evidence chain.
Proof-grade requires local-first by construction: the buyer owns the
receipts, the labels, the graph, and the signing keys — Tarka is the
evidence fabric, not the counterparty.

## Repo anchors

- Evidence endpoints: `services/case-api/src/case_api/main.py` (`/v1/compliance/evidence`, `/keys`, `/verify`)
- Hash chain + signature: same file, `_bundle_hash` / `_hash_chain` / `_bundle_signature`
- Offline verifier: `crates/tarka-cli/src/evidence_verify.rs` + `tarka verify` subcommand (cross-language parity: Python-signed bundles verify byte-for-byte)
- Replay gates: `crates/tarka-cli/src/replay.rs`, `batch-replay` scorecard
- Bitemporal reads: `services/graph-service/src/graph_service/main.py` (as_of / temporal filter)
- Completeness metric: `services/decision-api/src/decision_api/loop_metrics.py` (`compute_evidence_chain_completeness`)
