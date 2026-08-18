# Decision Context Graph Implementation Plan

> **For agentic workers:** Use TDD. Steps use checkbox syntax.

**Goal:** Native Decision SoR on graph-service + fail-soft writers + thin MCP + optional Semantica bridge stub.

**Architecture:** SQLite decision store in graph-service (testable SoR); optional Janus mirror as `Decision` entities; evaluate/AgentRun/disposition write fail-soft; Semantica mirror behind flag.

**Tech Stack:** FastAPI graph-service, sqlite3, httpx clients, stdio MCP JSON-RPC minimal.

**Global Constraints:** decision-api remains allow/deny authority; Semantica never on hot path; writers never fail parent request; pin Semantica if bridge enabled.

## Files

| File | Role |
|------|------|
| `services/graph-service/src/graph_service/decision_context_store.py` | SQLite SoR: record, get, chain, impact, search, invalidate |
| `services/graph-service/src/graph_service/decision_context_api.py` | Pydantic + route handlers |
| `services/graph-service/src/graph_service/main.py` | Mount routes; Decision in labels |
| `services/graph-service/tests/test_decision_context.py` | Store + HTTP tests |
| `packages/shared-core/tarka_shared/decision_graph_client.py` | Fail-soft HTTP client |
| `services/decision-api/.../evaluate/pipeline.py` (or outcome) | Write evaluate decisions |
| `services/investigation-agent/.../agent_run_store.py` | Write agent_advise |
| `services/case-api/...` | Write human_disposition on status |
| `services/tarka-mcp/` | Thin MCP stdio tools |
| `services/semantica-bridge/` | Optional mirror + smoke |
| `scripts/oss/decision_context_chain_smoke.py` | Offline golden chain |

## Tasks

- [x] Wave 1: store + HTTP (TDD)
- [x] Wave 2: client + writers
- [x] Wave 3: tarka-mcp
- [x] Wave 4: semantica-bridge stub + smokes
- [x] Mark design spec Status: Approved / In progress
