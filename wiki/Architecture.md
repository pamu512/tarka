# Architecture

Tarka is designed as modular services that can run independently or together.

## Core Flow

1. Event enters via SDK or ingest endpoint.
2. Decision API builds feature snapshot.
3. Rules, OPA, aggregates, and ML scoring run.
4. Entity tags are updated in Redis/Graph.
5. Audit trail is persisted.
6. Cases/workflows/investigation can consume outputs.

## Major Components

- `decision-api`: real-time evaluation, rules, policy, tagging
- `case-api`: investigations, workflows, SAR/disputes
- `graph-service`: entity graph + analytics
- `ml-scoring`: heuristic + adaptive anomaly scoring
- `feature-service`: feature normalization and enrichment
- `event-ingest`: async intake and fan-out
- `analytics-sink`: ClickHouse metrics/history
- `graphql-gateway`: unified query/mutation endpoint
- `integration-ingress`: KYC/OSINT/integration adapters
- `investigation-agent`: analyst assistant with guarded tools

## Data Stores

- PostgreSQL: cases, audit-oriented records
- Redis: tags, cache, nonce/session style runtime data
- Neo4j: entity relationships and graph tags
- ClickHouse: analytical event history
