# Auth path vs forensics path

Ojuri-style split: **auth decision must not wait on LLM / heavy graph upsert / investigation agents.**

| Path | Includes | Budget |
|---|---|---|
| **Auth** | JSON/Rust rules, Redis velocity, optional ML score, optional sync loyalty redeem bridge (hard timeout + circuit) | `TARKA_AUTH_PATH_P99_BUDGET_MS` (default 250 ms soft ops target) |
| **Forensics** | Shadow LLM / Ollama, investigation-agent, async graph upsert, NATS analytics | Never blocks auth response |

## Loyalty bridge

- Sync only on redeem checkpoint / redeem event type.
- Timeout: `TARKA_LOYALTY_ABUSE_TIMEOUT_SECONDS` (default 2s).
- Circuit: `TARKA_LOYALTY_ABUSE_CIRCUIT_FAILURE_THRESHOLD` / `_RECOVERY_SECONDS`.
- On open/fail: tags `enrichment:loyalty_circuit_open` or `enrichment:loyalty_bridge_failed` — decision continues.

## Posture

`GET /v1/ops/evaluation-posture` → `auth_path` block.
