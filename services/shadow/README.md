# tarka-shadow (library)

Python package **`shadow`** — hooks, prompts, and NATS OSINT helpers used **in-process** by the orchestrator (e.g. `shadow.hooks.resolve_case`).

**This is not the HTTP Shadow product.**

| Want | Use |
|------|-----|
| Ingest `POST /v1/analyze` | [`../shadow_agent/`](../shadow_agent/) |
| Desktop forensics | [`../../tools/shadow/`](../../tools/shadow/) |
| Brand map | [`../SHADOW.md`](../SHADOW.md) |

CI installs this package for unit tests (`pip install -e ./services/shadow[dev]`). Do not add a Dockerfile or compose service here.
