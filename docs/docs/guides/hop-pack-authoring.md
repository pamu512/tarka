# Authoring hop FLAG packs

Evaluate already has graph pack atoms (`has_etype`, `has_multi_id`, `sibling_prior_flag`). Shipped Observe examples:

- `graph_v1_uses_device_v1.json` — `USES_DEVICE`
- `graph_v1_has_instrument_v1.json` — `HAS_EMAIL` / `HAS_PHONE` / `HAS_CARD`
- `graph_v1_has_list_v1.json` — list hop

Empty `GRAPH_SERVICE_URL` means hops are off. The pack must not FLAG. The receipt says `graph:missing`. No invented neighbors.

Desk `/rules` can emit the same `when_ast` `graph_v1` JSON. Promote stays human on `/ops/shadow`.
