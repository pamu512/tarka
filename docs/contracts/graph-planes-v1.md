# Graph planes v1

Two planes. Never merge in marketing.

## A — Decide-time hops

Named hops on the evaluate receipt. Empty `GRAPH_SERVICE_URL` → `graph:missing`. No sibling identity invented. Hop packs `mode=shadow` until promote gates pass (human if ungated).

`parties[]` persist when the caller sends them. `entity_type` if present must be a registered vtype; unsigned types are refused. Empty graph still invents no edges.

## B — Offline ring / collusion jobs

Research / sidecar only. **Never** on the evaluate path. Empty `GRAPH_SERVICE_URL` still hops off (`graph:missing`); the job does not invent neighbors from an empty hop plane.

**Request** (`tarka.ring_job_request/v1`): `schema_id`, `tenant_id`, plus export `subgraph` + `labels`, or labeled `export[]` rows (`subgraph_snapshot` + `y_label` — edges derived), or raw `edges`. Invalid schema / tenant / shape → `ValueError`.

**Response** (`tarka.ring_job_response/v1`): `schema_id`, `tenant_id`, `ring_score[]`, `tags[]`, `live: false`. Degree-count heuristic v1. **Never** live ALLOW/DENY/FLAG. Not “GNN live”.

Writer (`write_ring_observe_drafts`) runs the job then `observe_drafts_from_ring`: Observe drafts (`mode=shadow`, `authored_by=seed`, source `hil:ring:{entity_id}`). Empty tags mint nothing. Never auto Active. Promote only via existing gates/human. This plane does not write live FLAG.

## C — Hunt depth (AGE)

Day-1 Hunt is depth-1. Empty `GRAPH_SERVICE_URL` turns Hunt off (same as hops). On-plane `GET /v1/subgraph` emits `tarka.hunt_depth/v1` (`depth_requested` / `depth_applied` / `degrade_reason`). Walk cap is `hunt_depth_max=1`. See [hunt-depth-v1](hunt-depth-v1.md).
