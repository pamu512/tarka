# GNN label loop (offline)

This is a **label + holdout loop**, not a live GNN. Evaluate still decides allow / deny / flag / review in Rust packs. `GRAPH_GNN_BETA_URL` empty (the compose default) means evaluate keeps `ring_score` `heuristic_v1` with `gnn_claim_allowed: false`.

## What exists today

1. **Evaluate snapshot** — `payload_snapshot.subgraph_snapshot` plus a JSONL receipt under `CALIBRATION_DATA_DIR`. Identity is hop v1.2 `(tenant_id, vtype, id)` — `user:abc` and `device:abc` are different vertices. Fields: named edges (type kept, not rewritten to RELATED), user/bridge vertices that were actually returned from graph-service, `trace_id`, `entity_id` / `user_id`, required evaluate `role`.
2. **Empty `GRAPH_SERVICE_URL`** — snapshot status is `graph:missing`. Neighbors are not invented from `party_graph` or anywhere else.
3. **Labels** — `y_label` + `why` from the existing y_label store (analyst override). Late chargeback sits on the same record as two fields: raw `dispute_outcome` and `chargeback_class` (`FRAUD` / `FRIENDLY` / `SERVICE` / `UNKNOWN`). A signed processor webhook `POST /v1/webhooks/late-label` binds those fields to the original evaluate receipt by `trace_id` (or `evaluation_token`). It does not reconstruct features. No snapshot → label is still recorded, `trainable: false`. Outcome other than `FRAUD` is still a label. There is no chargeback inbox or case CRM here.
4. **Export** — labeled rows `(subgraph_snapshot, y_label)` only. Unlabeled receipts are dropped.
5. **Train / gate** — offline 1-layer neighborhood aggregation + logistic regression. Holdout must **strictly beat** `heuristic_v1` (`ring_score`) on the same holdout. If it does not, serve stays off.
6. **Serve** — only if the gate file has `serve_allowed: true`. Point `GRAPH_GNN_BETA_URL` at `python -m decision_api.gnn_loop` (POST `/v1/graph-risk`). The overlay is a score. It never allow/denies. Graph-service never raises into evaluate when the URL is empty or the scorer fails.

## Receipts without edges

A labeled receipt with no named edges **cannot train a GNN**. Export may still write the row with `trainable: false`. The trainer skips those rows.

## Do not turn this on in compose

Buyer-desk / Lite / default compose must keep `GRAPH_GNN_BETA_URL` unset. Empty URL is heuristic. Do not add a default URL.
