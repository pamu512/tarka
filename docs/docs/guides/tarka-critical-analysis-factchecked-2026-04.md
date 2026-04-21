# Tarka Critical Analysis (Fact-Checked, Apr 2026)

This document fact-checks the claims in `Critical Tech Stack Analysis.pdf` against the current `tarka` repository state.

## Scope and method

- Source analyzed: `/Users/pamu/Downloads/Critical Tech Stack Analysis.pdf`.
- Verification basis: implementation files under `services/`, contracts under `contracts/openapi/`, and architecture docs in `docs/docs/`.
- Goal: separate **implemented facts** from **aspirational/misaligned claims** and produce a corrected technical assessment.

## Claim-by-claim verdict matrix


| PDF claim                                                                                      | Verdict                                                 | Repository evidence                                                                                                                                                | Notes                                                                                                                                 |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| Tarka frames fraud as identity + orchestration continuity, not only model accuracy.            | **Verified**                                            | `services/decision-api/src/decision_api/schemas.py`, `services/decision-api/src/decision_api/main.py`                                                              | `agent_context` and orchestration telemetry are first-class evaluate inputs.                                                          |
| Persistent pseudonymous IDs (HMAC-derived) are used for continuity across trust boundaries.    | **Partially verified**                                  | `services/decision-api/src/decision_api/consortium.py`, `services/decision-api/src/decision_api/consortium_api.py`                                                 | HMAC-scoped IDs exist for consortium signal sharing; broad "all continuity everywhere" phrasing is wider than current implementation. |
| Orchestration telemetry includes correlation IDs, tool sequence metadata, retry/error context. | **Verified**                                            | `services/decision-api/src/decision_api/schemas.py`                                                                                                                | `OrchestrationIn` includes `turn_id`, `tool_names_ordered`, `tool_sequence_digest`, `tool_retry_count`, and `plan_digest`.            |
| Tarka emphasizes explainable decisioning ("reasoning with reasons").                           | **Verified**                                            | `services/decision-api/src/decision_api/schemas.py`, `services/decision-api/src/decision_api/inference_build.py`, `services/decision-api/src/decision_api/main.py` | `inference_context` carries `driver_reasons`, `driver_explain`, top signals, and recommended action hints.                            |
| Stack includes ClickHouse for analytics workloads.                                             | **Verified**                                            | `services/analytics-sink/src/analytics_sink/main.py`, `services/analytics-sink/src/analytics_sink/config.py`                                                       | ClickHouse is implemented in analytics sink and exposed via analytics endpoints.                                                      |
| Core decision/microservices are Golang.                                                        | **Unsupported / inaccurate**                            | Repo-wide file scan: no `go.mod`, no `*.go`                                                                                                                        | Runtime services are implemented in Python/FastAPI in this repo.                                                                      |
| Ingestion layer is Rust-based.                                                                 | **Unsupported / inaccurate**                            | Repo-wide file scan: no `Cargo.toml`, no `*.rs`                                                                                                                    | Event ingest service is Python/FastAPI (`services/event-ingest`).                                                                     |
| PebbleDB is a low-latency metadata store in the runtime stack.                                 | **Unsupported / inaccurate**                            | No Pebble/PebbleDB runtime implementation found                                                                                                                    | Redis/Postgres/Neo4j/ClickHouse are the implemented storage components.                                                               |
| Decision API is Apollo GraphQL federation based.                                               | **Unsupported / inaccurate**                            | `services/graphql-gateway/src/graphql_gateway/main.py`, `services/graphql-gateway/src/graphql_gateway/schema.py`                                                   | GraphQL exists, but gateway is Strawberry + FastAPI, separate from the REST Decision API.                                             |
| AWS Lambda is the stateless decision execution substrate.                                      | **Unsupported / inaccurate**                            | Service runtime under `services/`* + deploy manifests under `deploy/`                                                                                              | Implemented runtime is containerized microservices; no Lambda decision execution path is present.                                     |
| Modular architecture introduces an integration tax (contracts, versioning, failure modes).     | **Verified**                                            | `docs/docs/architecture.md`, `contracts/openapi/*.yaml`, multi-service layout in `services/`*                                                                      | This is consistent with the architecture and codebase structure.                                                                      |
| Immutable decision records are required for replay and late-arriving labels.                   | **Verified**                                            | `services/decision-api/src/decision_api/decision_log.py`, `scripts/replay/replay_decision_logs.py`, `docs/docs/guides/immutable-decision-records.md`               | Canonical decision log schema/writer and replay tooling are implemented.                                                              |
| Graph/ring analytics are integrated in decisioning ecosystem.                                  | **Verified**                                            | `services/graph-service/src/graph_service/main.py`, `contracts/openapi/graph-service.yaml`                                                                         | Includes `entity-risk` and `ring-suspicion`; decision context also includes graph risk fields.                                        |
| External signal connectors are part of the model for augmentation.                             | **Verified**                                            | `services/decision-api/src/decision_api/external_signals.py`, `services/decision-api/src/decision_api/main.py`                                                     | Generic connector interface exists; Scameter adapter is implemented and wired.                                                        |
| Explainability can expose decision boundaries to adversaries.                                  | **Plausible risk (not directly testable as code fact)** | Explainability fields in `services/decision-api/src/decision_api/schemas.py` and outputs in `main.py`                                                              | This is a security posture concern, not a binary implementation claim.                                                                |


## Corrected technical stack summary (as implemented)

- **Primary language/runtime:** Python 3.11+ with FastAPI services.
- **Core data systems:** Redis (realtime tags/aggregates), Postgres (cases/audit), Neo4j (graph path), ClickHouse (analytics sink).
- **Messaging:** NATS JetStream for async ingest/stream paths.
- **Gateway/API composition:** REST-first service APIs plus a Strawberry GraphQL gateway.
- **Fraud decision fabric:** rules + ML + graph + counters + external connectors + explainability context.
- **Auditability:** immutable decision log writer plus replay tooling and evidence bundle generation.

## Engineering risks that remain valid after correction

1. **Contract drift across modular services** can create silent failure modes unless contract tests and compatibility checks remain strict.
2. **Latency and fallback behavior** across upstream dependencies (graph, ML, external connectors) must be continuously observed and tuned.
3. **Explainability surface hardening** is necessary to avoid leaking high-value boundary clues to adversarial actors.
4. **Scoped identity tension** remains: privacy-preserving scoping can reduce cross-tenant abuse visibility without robust consortium sharing.
5. **Replay fidelity limits** still apply when rules/models/configs evolve over time despite immutable logging.

## Bottom line

The PDF is directionally strong on architectural philosophy (continuity, telemetry, explainability, replay) and on real operational risks (integration tax, drift, adversarial adaptation). Its concrete runtime stack assertions around Golang/Rust/PebbleDB/Apollo Federation/AWS Lambda do **not** match the current repository implementation and should be treated as aspirational or misattributed rather than implemented facts.