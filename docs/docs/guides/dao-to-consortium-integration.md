# DAO outcomes → consortium APIs (v1.2)

This guide satisfies the **v1.2 DAO slice** exit criterion: how **off-chain** governance outcomes flow into Tarka’s **opt-in** consortium signals without coupling core services to a chain.

## Sequence

1. **DAO records an outcome** (vote, multisig, snapshot). Persist a **versioned** envelope; see `[contracts/examples/dao-attestation-v1.example.json](../../../contracts/examples/dao-attestation-v1.example.json)` for a canonical JSON shape (EIP-191 message + optional IPFS CID).
2. **Operator or worker maps the outcome** to consortium HTTP calls against **your** decision-api:
  - Share a signal: `POST /v1/consortium/share` (or `python scripts/consortium_adapter/cli.py share ...`).
  - Optional feedback after review: `POST /v1/consortium/feedback`.
  - Tenant trust weight: `POST /v1/consortium/trust` (within documented bounds).
3. **Evaluate behavior**: consortium aggregates are read during `POST /v1/decisions/evaluate` when `**CONSORTIUM_ENABLED`** and Redis are configured; tenant isolation remains enforced (hashed entity identifiers, tenant-scoped trust).

## Reference adapter

Use `**[scripts/consortium_adapter/README.md](../../../scripts/consortium_adapter/README.md)**` for CLI flags, JSON Lines batch ingest, and Python `httpx` client patterns. The adapter is **not** a third-party SDK; it targets your deployment’s base URL and optional `X-API-Key`.

## Analyst dry-runs (ML)

For batch scoring against **ml-scoring** (separate from consortium), use `**[scripts/ml_batch_score.py](../../../scripts/ml_batch_score.py)`** and `**scripts/benchmarks/README.md**`.

## Security notes

- Treat attestations as **provenance hints** until your org defines verification (signature checks, replay windows, allow-listed DAO keys).
- Do not put cross-tenant PII into consortium payloads; align with `**[joinsonar-query-feedback-vs-consortium-api.md](joinsonar-query-feedback-vs-consortium-api.md)`** and `**[unit21-fraud-dao-vs-consortium-api.md](unit21-fraud-dao-vs-consortium-api.md)**`.