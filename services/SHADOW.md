# Shadow — one brand, three paths

**Shadow** is local-first forensic reasoning. Do not invent a fourth HTTP service.

| Path | Package / name | Use |
|------|----------------|-----|
| [`shadow_agent/`](shadow_agent/) | `tarka-shadow-agent` | **Production ingest sidecar** — `POST /v1/analyze`, audit write, Ollama. Wired from orchestrator via `SHADOW_AGENT_URL`. |
| [`shadow/`](shadow/) | `tarka-shadow` | **Python library only** — hooks (`resolve_case`), NATS OSINT helpers, prompts. Imported by orchestrator; not a container in default compose. |
| [`../tools/shadow/`](../tools/shadow/) | desktop console | **Analyst workstation** — Vite/Tauri + local sidecar (`:8742`). Not part of default Lite / prod Helm. Frontend proxies `/api/shadow-llm` for local-only use. |

## Naming rules

- Docs and ops say **“Shadow agent”** → `services/shadow_agent`.
- Code imports `from shadow.…` → library under `services/shadow`.
- “Shadow desktop / forensics console” → `tools/shadow`.
- Never name a new compose service `shadow` without a suffix (`shadow_agent`, `shadow-desktop`).
