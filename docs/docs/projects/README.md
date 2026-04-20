# Module Projects Roadmap

This section tracks each major module as its own project with a focused roadmap.

## How to Use

- Each project page contains scope, current gaps, and phased roadmap items.
- Use the same issue IDs and Friday milestones from the main execution board.
- Treat `Now` as active work, `Next` as near-term queue, and `Later` as strategic backlog.
- For **cross-module release planning**, see [Journey ship bundles](../guides/journey-ship-bundles.md) (J1–J5) alongside the [OSS dependency DAG](../guides/oss-ship-order-dependencies.md).

## Modules

- [Decision API](decision-api-project.md)
- [Case API](case-api-project.md)
- [Graph Service](graph-service-project.md)
- [ML Scoring](ml-scoring-project.md)
- [Feature Service](feature-service-project.md)
- [Integration Ingress](integration-ingress-project.md)
- [Frontend](frontend-project.md)
- [Python SDK](sdk-python-project.md)
- [TypeScript SDK](sdk-typescript-project.md)
- [Mobile SDKs (Android + iOS)](sdk-mobile-project.md)
- [Analytics Sink](analytics-sink-project.md)
- [Investigation Agent](investigation-agent-project.md) — commercial packaging: [Saarthi Pro vs OSS](../guides/saarthi-pro-vs-oss.md)

## Service overview pages (ports & endpoints)

Short write-ups that complement project roadmaps and the [API Reference](../api-reference.md):

- [Decision API](../services/decision-api.md) · [Graph Service](../services/graph-service.md) · [Case API](../services/case-api.md) · [Feature Service](../services/feature-service.md) · [ML Scoring](../services/ml-scoring.md) · [Investigation Agent](../services/investigation-agent.md)

No dedicated **services/*.md** page yet for these — use the [API Reference](../api-reference.md): [Integration Ingress](../api-reference.md#integration-ingress) and [Collaboration Chat Bridge](../api-reference.md#collaboration-chat-bridge) ship OpenAPI under `contracts/openapi/`; [Event Ingest](../api-reference.md#event-ingest) and [Analytics Sink](../api-reference.md#analytics-sink) are documented there as HTTP tables only (**no** published `contracts/openapi` spec yet). The [GraphQL gateway](../api-reference.md#graphql-gateway) is **code-first** Strawberry GraphQL (no `contracts/openapi` entry).
