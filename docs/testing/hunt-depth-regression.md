# Hunt depth regression (Path B)

Runnable checklist for the next agent. SUPPORT tone. Path B is shipped (D7.4). Do not raise `hunt_depth_max`. Do not implement Path A in this pack.

Contract: [hunt-depth-v1](../contracts/hunt-depth-v1.md). Operator day-1: [graph-analysis — Day-1 Hunt depth](../docs/guides/graph-analysis.md#day-1-hunt-depth). Honesty lock: [CLAIM_LOCK](../compliance/CLAIM_LOCK.md). Leftovers + Hunt residual: [SUPPORT.md](../../SUPPORT.md).

Empty `GRAPH_SERVICE_URL` = Hunt/hops off (UX0 `PlaneOff`). `depth=5` must cap to `depth_applied=1` with `degrade_reason=hunt:depth_capped`. Leftovers / queue are not a CRM.

## graph-service (D7.4)

From `services/graph-service`:

```bash
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_hunt_depth_api.py tests/test_hunt_net.py
```

Expect:

- `hunt_depth_max` stays `1` (`test_path_b_hunt_depth_max_stays_one`)
- `depth=1` → `depth_applied=1`, `degrade_reason` null
- `depth=5` (and 2, 3, default 2) → walk arg `1`, `depth_applied=1`, `degrade_reason=hunt:depth_capped`
- AGE walk stays `MATCH (root)-[e]-(nb)` for requested 1 and 5 (no star-range, no `age_unnest`)

## decision-api empty URL

From `services/decision-api`:

```bash
PYTHONPATH=src:../shared:../../packages/shared-core:../.. pytest tests/test_hunt_hop_empty_url.py
```

Expect: empty URL → `graph:missing`; no subgraph fetch; no invented neighbors; evaluate does not block.

## frontend honesty

From `frontend` (`node_modules` may be a symlink to the main checkout; do not commit it):

```bash
npm test -- src/domain/huntDepthHonesty.test.ts src/components/HuntDepthHonestyStrip.test.tsx src/pages/GraphInvestigationPage.test.tsx src/pages/PlaneOff.test.tsx
```

Expect: empty `VITE_GRAPH_SERVICE_URL` is plane-off English (not a spinner or fake nodes). Live `/v1/subgraph` with `depth_applied=1` + `hunt:depth_capped` shows those numbers, not the stub.

## contract + CLAIM_LOCK

From repo root:

```bash
python3 infra/scripts/ci/test_hunt_depth_contract.py
```

Forbidden-claim scan is `test_hunt_depth_contract.py` (`FORBIDDEN` + D7.5 new-copy paths). Run it; do not paste those tokens into new buyer copy. Allowed only on [hunt-depth-v1 Out of scope](../contracts/hunt-depth-v1.md#out-of-scope) and the CLAIM_LOCK must-not column.

CLAIM_LOCK Hunt rows: left cell stays Path B depth-1 + empty URL off. Right cell keeps the must-nots.

## Doc links

Resolve each new relative link from its file. Fail if the target is missing.

- [hunt-depth-v1](../contracts/hunt-depth-v1.md)
- [graph-analysis Day-1](../docs/guides/graph-analysis.md#day-1-hunt-depth)
- [CLAIM_LOCK](../compliance/CLAIM_LOCK.md)
- [SUPPORT.md](../../SUPPORT.md)
- [graph-planes-v1](../contracts/graph-planes-v1.md)
- [test_hunt_depth_api.py](../../services/graph-service/tests/test_hunt_depth_api.py)
- [test_hunt_hop_empty_url.py](../../services/decision-api/tests/test_hunt_hop_empty_url.py)
- [test_hunt_depth_contract.py](../../infra/scripts/ci/test_hunt_depth_contract.py)

## Out of this pack

Do not change `hunt_depth_max`. Do not ship Path A. Do not add product SKUs, GNN live, or a CRM. D8 / D9 / D10 stay elsewhere. D10: git is backup, not this PR.
