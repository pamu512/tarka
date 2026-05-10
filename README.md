# Tarka

Tarka delivers a local-first, audit-first fraud plane: orchestration and rules run on hardware you control, while durable relational audit rows—not ephemeral caches—are the system of record for disposition and rationale. Optional forensic LLMs reuse the same ingestion contract so analysts prove hypotheses from data you already committed, not vendor APIs.

---

## Hardware requirements

| Resource | Guidance |
|----------|----------|
| **RAM** | **24GB or more** recommended when running **Llama 3.2-class** models locally (e.g. via Ollama behind the Shadow sidecar). Smaller footprints are fine for API-only paths that skip local LLM inference. |
| **CPU** | Recent **Apple Silicon** or **x86_64** with hardware AES; multi-core helps parallel rule + HTTP fan-out. |
| **Disk** | **SSD** with **≥20GB** free for base container layers plus model pulls if you enable local inference. |
| **Software** | **Docker Compose v2** (or compatible **Docker Engine** / **Docker Desktop**) for the Phase 9 bootstrap below. |

---

## Bootstrap the v2 ingest stack (Phase 9)

These scripts build and run the **rule engine**, **Shadow sidecar**, and **orchestrator** described in [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md). They must be run from the **repository root** with the Docker daemon running.

```bash
./scripts/phase9/01-build-v2-ingest-stack.sh
./scripts/phase9/02-up-v2-ingest-stack.sh
./scripts/phase9/03-verify-v2-ingest-stack.sh
```

**Optional:** set `TARKA_SHADOW_API_KEY` before step 2 if you change the default API token (compose and orchestrator must agree).

**Success:** step 3 prints `OK` and `GET http://127.0.0.1:8790/health/full` returns HTTP **200** with a `services` array (orchestrator, rule engine, shadow). Default ports: orchestrator **8790**, rule engine **8778**, shadow **8801**.

**Stop the stack:** `docker compose -f deploy/docker-compose.v2-ingest.yml down` (from the repo root).

---

## Repository map

| Path | Role |
|------|------|
| [`tarka_v2_core/`](tarka_v2_core/) | Audit-first **v2** services: ingestor schema, rule engine, orchestrator, shadow agent, shared DB models. |
| [`tarka_v2_ui/`](tarka_v2_ui/) | Next.js UI for demos and operator views. |
| [`legacy_attic/`](legacy_attic/) | Archived monolith-era trees kept for reference; not required for the v2 ingest compose file above. |
| [`docs/onboarding.md`](docs/onboarding.md) | Nix shell, Pulumi triple-DB, and broader platform onboarding. |
| [`docs/docs/guides/aspirational-gaps-execution-plan.md`](docs/docs/guides/aspirational-gaps-execution-plan.md) | Phased roadmap (includes **Phase 9** bootstrap deliverables). |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Bug reports, pull requests, PR checklist, and AST policy for contributors. |

---

## Legacy installer (optional)

The historical Python CLI and broader compose profiles still live in the repo (for example `python tarka.py install` and `deploy/docker-compose.*.yml`). Prefer the **Phase 9** path above when you only need the v2 **ingest + policy + optional shadow** loop on one machine.

---

## License

Application code in this repository is **Apache-2.0** unless a subdirectory states otherwise. Some optional backends (for example certain graph databases) carry their own licenses; see **`LICENSE-DEPENDENCIES.md`** when you enable them.
