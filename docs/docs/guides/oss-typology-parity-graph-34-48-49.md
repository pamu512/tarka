# OSS #34 / #48 / #49 — typologies, feature parity, graph checkpoints

## #34 Typology layer (Decision API)

- **Definitions:** `services/decision-api/rules/typology_definitions_v1.json` — reference typologies (`velocity_abuse`, `new_payee_risk`, `amount_stress`) with member JSON rule ids, optional feature predicate bonuses, and breach thresholds.
- **OSS #46:** named **`predicate_ref`** + **`typology_predicate_registry_v1.json`** — see [oss-typology-dsl-46.md](./oss-typology-dsl-46.md).
- **Evaluation:** After rule + OPA hits are merged, `evaluate_typologies()` scores each typology from **rule hit ids** + **feature snapshot** predicates (reuses `_match_condition` — no second rule engine pass).
- **Audit:** `payload_snapshot.typologies` (per-typology score, breach level, contributing rules/features, disposition label) and `payload_snapshot.typology_summary` (worst breach + driver id).
- **Reload:** typology JSON is loaded at startup and on `POST /v1/admin/rules/reload`.

## #48 Feature Service parity verifier

- **UI:** **Governance → Feature tools** (`/ops/features`) proxies the feature-service via nginx (`/api/features/`) so operators can query velocity and run parity without curl.
- **Endpoint:** `POST /v1/internal/parity/verify` — body: `tenant_id`, `entity_id`, `payload`, `expected` (map of velocity key → expected float), `epsilon`.
- **Behavior:** Reads Redis via the same `AggregateStore` as `/v1/velocity/query`. Returns **200** with `ok: true` when all keys within epsilon; **409** with drift detail when not.
- **Fixtures:** Use the same Redis as decision-api for production parity; for CI, use a scratch Redis + known JSONL replay.

## #49 Graph checkpoint profiles

- **Registry:** `services/graph-service/rules/checkpoint_profiles_v1.json` — profiles `minimal` / `standard` / `deep` with `risk_score_multiplier` (and **`max_neighbor_hops`** (1–5) wiring **community traversal depth** in entity-risk: Neo4j path `*1..depth`, JanusGraph BFS).
- **API:** `GET /v1/checkpoint-profiles`, `POST /v1/admin/checkpoint-profiles/reload`, `GET /v1/analytics/entity-risk?checkpoint=minimal`.
- **Decision API:** Pass checkpoint via `metadata.graph_checkpoint` (or `GRAPH_CHECKPOINT_METADATA_KEY`) or `payload.graph_checkpoint`; forwarded to graph-service as `checkpoint` query param. When **OSS #42** graph selective routing is enabled, the Decision API can also choose a checkpoint from `graph_routing_policy_v1.json` based on pre-graph base score and event type, and records the decision under `audit.payload_snapshot.graph_routing`.
