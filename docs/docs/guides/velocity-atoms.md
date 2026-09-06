# Velocity atoms (canonical keys)

Strategy composes count / sum / distinct over a window by using the **existing** evaluate feature keys. This is not a second language. Missing features stay missing on the receipt.

| Atom | Key examples |
|------|----------------|
| count | `event_count_5m`, `event_count_1h`, `event_count_24h`, `event_count_7d` |
| sum | `sum_amount_1h`, `sum_amount_24h` |
| unique_count | `distinct_device_id_24h`, `distinct_ip_address_24h`, `distinct_session_id_24h` |
| computed | `event_count_1h_share_24h` (`event_count_1h / event_count_24h`) |

`event_count_1h_share_24h` is **not** a Redis key. Evaluate attaches it only when `event_count_24h` ≥ `TARKA_BASELINE_WARMUP_24H` (default 10). Thin history omits the key (missing, not `0`). `score_delta` on this assist is not a calibrated score — Observe calibration comes later.

`rate` and `baseline_ratio` are not evaluate features. Do not invent them in packs.

Desk `/rules` sentences and the AI pack-author allow-list must use these names (not `tx_count_*`).

See also [velocity-counter-rule-keys.md](./examples/velocity-counter-rule-keys.md).
