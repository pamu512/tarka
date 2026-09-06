# Authoring hop FLAG packs

**Graph** here is the identity hop (`GRAPH_SERVICE_URL` / AGE). Decision-context SQLite is a separate SoR — it is not the Graph SKU.

Evaluate already has graph pack atoms (`has_etype`, `has_multi_id`, `sibling_prior_flag`). Desk `/rules` has two sentences:

- **Share-edge** — `has_etype` only. No `FLAG` tag. This person shares a signed etype.
- **Trust FLAG** — `has_etype` AND (`has_multi_id` OR `sibling_prior_flag`). Same `when_ast` as the shipped packs. Copy names sibling prior FLAG.

Shipped Observe examples:

- `graph_v1_uses_device_v1.json` — `USES_DEVICE`
- `graph_v1_has_instrument_v1.json` — `HAS_EMAIL` / `HAS_PHONE` / `HAS_CARD`
- `graph_v1_has_list_v1.json` — list hop

Empty `GRAPH_SERVICE_URL` means hops are off. The pack must not FLAG. The receipt says `graph:missing`. No invented neighbors.

Desk `/rules` can emit the same `when_ast` `graph_v1` JSON. Promote stays human on `/ops/shadow`.
