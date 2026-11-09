# Evaluate persists device signals and party-graph edges

**Date:** 2026-10-14  
**Status:** Design — not implemented.  
**Slice:** 1 of the finish-the-thin-surfaces pass. Boards, the holdout model, the location seal, and the duplicate ML packages are later slices.

## Goal

One write path for device signals and party-graph edges.

- An install shows only edges and reputation that its own evaluate calls wrote.
- `make demo` fills tenant `demo` by posting those same evaluate calls.
- Request handlers do not invent rows when the stores are empty.

## What already happens

`packages/shared-core/tarka_shared/decision_graph_payload.py` `build_evaluate_objects` turns one evaluate into a Person, a Device, and a `USED_DEVICE` link when `device_context.device_id` or a payload device id is present. It also emits session, IP, email, phone, card, account (`OWNS`), `MADE_PAYMENT`, and `PERFORMED_LOGIN` when those fields are on the request.

`services/decision-api/src/decision_api/main.py` `_graph_upsert` posts those objects after the decision, in the background, only when `GRAPH_SERVICE_URL` is set. An empty URL returns the decision and writes no edges. `disable_graph` skips the write. The decision does not wait on the graph.

`evaluate/pipeline.py` already records fingerprints and entity-device links when `fingerprint_store._client` / `entity_link_store._client` is set and the request is not a shadow duplicate. `main.py` calls `set_client` for those two stores from the tag Redis client.

`DeviceIntelligenceStore` in `device_intelligence.py` is never `set_client`'d and never called from evaluate. `update_device_reputation` raises `RuntimeError` when `_client` is missing. `get_device_reputation` returns `None` in that case.

`scripts/seed_demo_data.py` posts evaluate bodies for tenant `demo`, then `seed_graph` posts `/v1/entities` and `/v1/links` with a second vocabulary: entity type `User`, edges `USED`, `PAID`, `FORWARDED_TO`, `REFERRED`. `make demo` (`scripts/oss/up_desk.sh`) does not run this script. After health it runs `scripts/oss/walk_receipts.py`. `make product` does the same walk and must stay that way.

The edge evaluate writes for a device is `USED_DEVICE`. Hop copy that says `USES_DEVICE` is unchanged in this slice.

## Locked choices

- Rust packs still decide. This slice does not let device reputation allow, deny, or review.
- Missing reputation is an absent feature. It is not score `0` and not a default risk of `50`.
- A deny on this request is not `is_fraud_confirmed`. Late labels stay out of this slice.
- Shadow duplicate traffic does not read or write device intelligence, matching the fingerprint skip.
- No demo branch inside evaluate or graph handlers.
- The seed writes only tenant `demo`. It gains no `--tenant` flag.
- `make product` / `scripts/oss/up_product.sh` does not call the seed.

## Device intelligence on evaluate

Wire `device_intelligence.set_client` in the same lifespan block that sets `fingerprint_store` and `entity_link_store` (`decision-api` `main.py`).

**Read, before rules.** If the request is not shadow, `device_context.device_id` is non-empty, and `device_intelligence._client` is set:

- `get_device_reputation(tenant_id, device_id)`.
- When the result is a row, set `features["device_reputation_score"]` to `calculate_risk_score()`.
- When the result is `None`, leave the feature unset.

**Write, after the decision string exists, still before the HTTP return.** Same guards (not shadow, device id, client set):

- `update_device_reputation(tenant_id, device_id, decision, is_fraud_confirmed=False)`.
- `record_biometrics` only when `device_context.signals` has a dict under `typing`, `mouse`, `session`, or `bot_indicators`. Flat flags such as `is_vpn` do not count. Otherwise skip biometrics.
- `record_consortium_device(device_id, tenant_id, entity_id)`.
- `record_device_ip_velocity` when `payload["ip_address"]` or `device_context.signals["ip_address"]` is a non-empty string. Payload wins if both are set. Otherwise skip. The fingerprint store does not record IP.

This request’s decision is not part of the reputation feature used to score it. The write stores it for the next evaluate.

**Failures.**

- No Redis client: skip read and write. Do not add a degrade tag. Same silence as the fingerprint store when it is unwired.
- Client is set and a read or write raises: append `device_intelligence:unavailable` to `degrade_tags`. Do not fail the decision. Do not set `device_reputation_score` from a failed read.

Consortium counts are stored. They are not copied into rule features in this slice.

## Party-graph edge

`build_evaluate_objects` gains one link.

When payload `counterparty_entity_id` is a non-empty string, trimmed, and different from the evaluate `entity_id`:

- Emit a Person object for that id if the object list does not already contain it.
- Append a link `from_external_id` = the evaluate person, `to_external_id` = the counterparty, `relationship` = `TRANSACTED`.

Missing, blank, or equal to `entity_id`: no `TRANSACTED` link.

`_graph_upsert` already posts the object and link lists. It does not grow a second code path for this edge.

Shared devices stay two `USED_DEVICE` links to the same device id from two evaluate calls. This slice does not rename `USED_DEVICE` to `USES_DEVICE`.

Graph upsert stays background and fail-soft. Empty `GRAPH_SERVICE_URL` still writes nothing.

## Demo seed

`seed_graph`, `_graph_entities`, and `_graph_links` are removed. `main` no longer posts `/v1/entities` or `/v1/links`.

The demo story stays in the evaluate bodies:

- Shared device: Frank and Gina already evaluate with `dev_emulator_003`. That stays.
- Mule payment: a payment whose `entity_id` is the sender (`fraud_frank` toward `mule_ivan`, `fraud_gina` toward `mule_jane`) and whose payload `counterparty_entity_id` is the mule. The current mule loop that sets `entity_id` to the mule and `recipient` to the same mule changes to that shape. Amount and currency stay on the payload so `MADE_PAYMENT` still builds.
- Device signals stay on `device_context` of the evaluate body. They are not a side graph write.

`TENANT_ID` stays `"demo"`. Every evaluate body the seed posts uses that id.

**`make demo` cold path.** `scripts/oss/up_desk.sh`, after core-api and graph-service health succeed, and before `walk_receipts.py`:

```bash
python3 scripts/seed_demo_data.py \
  --decision-url "http://127.0.0.1:${CORE_PORT}/decisions" \
  --graph-url "http://127.0.0.1:${GRAPH_PORT}"
```

The `/decisions` prefix matches `walk_receipts.py` (`DECISION_API` default `http://127.0.0.1:8000/decisions`). The script default `--decision-url http://localhost:8000` stays for a standalone decision-api process. The demo hook passes the macroservice prefix.

The already-healthy short-circuit at the top of `up_desk.sh` still execs `walk_receipts.py` and does not re-seed.

Seed health rules for this hook:

- decision-api unhealthy: exit non-zero. `make demo` does not start the walk.
- graph-service unhealthy: exit non-zero. The seed does not post evaluates that would return decisions with no graph behind them.
- case-api or integration-ingress unhealthy: skip those sections and continue. They are not required for this slice. Today `main` aborts when case-api is down. That abort goes away so lite desk, which may not be running case-api, can still seed evaluates.

`up_product.sh` is not changed.

The seed does not poll the graph. Upsert remains asynchronous. This slice’s proof is the unit tests below, not a Hunt screenshot.

## Tests

- `build_evaluate_objects`: payload `counterparty_entity_id` set to a different id yields a `TRANSACTED` link. Blank, missing, and equal to `entity_id` yield none.
- Device intelligence: with a Redis client (fakeredis or the existing store test style), a prior `update_device_reputation` causes the next feature build to set `device_reputation_score` from `calculate_risk_score()`. With `_client is None`, the feature stays unset and no degrade tag is added. With a client whose `get_device_reputation` raises, the evaluate pipeline appends `device_intelligence:unavailable` and still returns `EvaluateResponse`. The store’s internal starting `base_reputation` of `50` stays as it is. That value is not copied into features until a row exists.
- Seed: a test loads `scripts/seed_demo_data.py` and asserts `TENANT_ID == "demo"`, `seed_graph` is gone, and mule payment bodies set `counterparty_entity_id` to the mule while `entity_id` is the referring fraudster. No seed URL ends in `/v1/entities` or `/v1/links`.
- `up_desk.sh` contains the seed invocation on the cold path. `up_product.sh` does not contain `seed_demo_data.py`.

## Out of this slice

- Desk boards (mule path, synthetic identity, review rings, social engineering, command center) still have their current handlers. They start reading this graph in the next slice.
- `USES_DEVICE` hop packs, `gnn_loop`, ML weights, location sealing, Semantica, schema-registry status, and `mockData.ts`.
- Waiting for the background graph upsert inside `make demo`.
- Treating decision `deny` as a fraud label.
