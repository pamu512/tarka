# Investigation-Agent RAG / Embeddings Matrix

This matrix documents how `services/investigation-agent` behaves across embedding and storage settings so operators can reason about fallback behavior.

## Runtime matrix

| `COPILOT_KNOWLEDGE_EMBEDDINGS` | Embedding key available (`COPILOT_EMBEDDING_API_KEY` or `OPENAI_API_KEY`) | Search mode in `search_knowledge` | Ingest result (`embeddings_stored`) | Operational note |
|---|---|---|---|---|
| `true` | yes | Hybrid semantic + keyword (weighted by `COPILOT_RAG_KEYWORD_WEIGHT`) | `true` | Best relevance and robust typo handling. |
| `true` | no | Keyword-only fallback | `false` | Safe degraded mode; still deterministic and local. |
| `false` | yes/no | Keyword-only | `false` | Explicitly disables vector storage for strict environments. |

## Storage matrix

| `BATCH_STORE_PATH` | Batch storage mode (`/v1/governance`, `/v1/batch/ingest`) | Durability profile |
|---|---|---|
| unset | `memory` | Ephemeral; lost on process restart. |
| set (writable path) | `disk+memory` | Survives process restart within TTL window; evicted by TTL and max-batch cap. |

## Guardrails and troubleshooting

- `POST /v1/batch/ingest` now returns `storage_mode` and `durable_until` so analysts can see TTL-derived retention directly in UI or logs.
- `GET /v1/governance` exposes `batch_storage_mode` and `batch_ttl_seconds` for deployment introspection.
- If embeddings are expected but `embeddings_stored=false`, verify key resolution order:
  1. `COPILOT_EMBEDDING_API_KEY`
  2. `OPENAI_API_KEY`
- If `BATCH_STORE_PATH` is set but storage still reports `memory`, ensure the path is writable by the service user.
