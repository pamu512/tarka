# Graph-risk / Ring-score challenger (offline label loop)

This is a **label + holdout loop**, not a live GNN. Desk copy: **Graph-risk / Ring-score challenger** — never “GNN live.” Evaluate still decides allow / deny / flag / review in Rust packs. Empty `GRAPH_GNN_BETA_URL` (the compose default) means evaluate keeps `ring_score` `heuristic_v1` with `gnn_claim_allowed: false`.

**RiskOps glass:** `GET /v1/ops/graph-risk-challenger?tenant_id=` and Settings → Graph-risk challenger strip. Export / Train / Enable shadow URL (only when `serve_allowed`) / Retire. Live FLAG/REVIEW still requires a **Promoted pack** that reads the score (`live_effect: pack_promote_only`).

## What exists today

1. **Evaluate snapshot** — `payload_snapshot.subgraph_snapshot` plus a JSONL receipt under `CALIBRATION_DATA_DIR`. Identity is hop v1.2 `(tenant_id, vtype, id)` — `user:abc` and `device:abc` are different vertices. Fields: named edges (type kept, not rewritten to RELATED), user/bridge vertices that were actually returned from graph-service, `trace_id`, `entity_id` / `user_id`, required evaluate `role`.
2. **Empty `GRAPH_SERVICE_URL`** — snapshot status is `graph:missing`. Neighbors are not invented from `party_graph` or anywhere else.
3. **Labels** — `y_label` + `why` from the existing y_label store (analyst override). Late chargeback sits on the same record as two fields: raw `dispute_outcome` and `chargeback_class` (`FRAUD` / `FRIENDLY` / `SERVICE` / `UNKNOWN`). A signed webhook `POST /v1/webhooks/late-label` binds those fields to the original evaluate receipt by `trace_id`, `evaluation_token`, or `decision_token`. It does not reconstruct features. No snapshot → label is still recorded, `trainable: false`. Outcome other than `FRAUD` is still a label. There is no chargeback inbox or case CRM here.

   The same webhook also accepts frontline / finance / evaluate joins (not a second product):

   | Path | How it lands | Observe |
   |---|---|---|
   | Chargeback (existing) | `dispute.outcome` → receipt; `label_kind` inferred (`fraud` / `other`); `source` defaults to `finance`; no `prior_override_id` | none |
   | False positive | `label_kind=fp` on a restrictive receipt (`DENY` / `REVIEW` / step-up). `y_label=0`. Optional `fp_cost` amount/currency or ordinal on the bind. Host Care/CRM POSTs this webhook — this repo has no Care UI. | Mints a human/seed Observe pack (`intent=soften`, `mode=shadow`). Same path as `POST /v1/webhooks/disposition`. A model did not evaluate and does not own live. |
   | Override → later fraud | Human overrode toward allow/clear (override receipt, same `evaluation_token`). Later fraud late-labels **that override receipt** with `prior_override_id`. Distinct from a chargeback with no override. | none |
   | Follow-on evaluate | Later evaluate on the same entity may bind `label_source=evaluate` to a **prior** receipt (`entity_id` + `later_trace_id`, or an explicit `decision_token`). One learning join, not a CRM case. | none |

   `source` is an ingest tag (`care` / `finance` / `crm` / `evaluate`). `crm` means a host CRM pushed the webhook. This repo does not grow a Care/CRM inbox.
4. **Export** — labeled rows `(subgraph_snapshot, y_label)` only. Unlabeled receipts are dropped.
5. **Train / gate** — offline 1-layer neighborhood aggregation + logistic regression. Holdout must **strictly beat** `heuristic_v1` (`ring_score`) on the same holdout. If it does not, serve stays off.
6. **Serve** — only if the gate file has `serve_allowed: true`. Point `GRAPH_GNN_BETA_URL` at `python -m decision_api.gnn_loop` (POST `/v1/graph-risk`). The overlay is a score. It never allow/denies. Graph-service never raises into evaluate when the URL is empty or the scorer fails.

## Receipts without edges

A labeled receipt with no named edges **cannot train a GNN**. Export may still write the row with `trainable: false`. The trainer skips those rows.

## Desk bars (Track-3 planning)

| Bar | Value |
|-----|-------|
| Code floor to train | ≥ **8** trainable edged labeled rows (`train_and_gate`) |
| Planning label density | ≥ ~1e3 late labels (glass only) |
| Planning edged events | ≥ ~1e5 (or 30d continuous) — glass only |
| Serve gate | Holdout AUC **strictly beats** `heuristic_v1` |

## Do not turn this on in compose

Buyer-desk / Lite / default compose must keep `GRAPH_GNN_BETA_URL` unset. Empty URL is heuristic. Do not add a default URL.
