# Lighter managed-container deployment path

This path is for teams that want partial Tarka adoption without operating full Kubernetes on day one.

Use it for early production pilots, smaller module footprints, or organizations standardizing on managed container runtimes (for example Cloud Run or ECS/Fargate).

---

## Good candidates for lighter runtime

| Service | Notes |
|---|---|
| `decision-api` | Core scoring API; pair with managed Postgres + Redis |
| `case-api` | Works well when Postgres is managed and latency to decision-api is stable |
| `integration-ingress` | Suitable for webhook and adapter flows |
| `graphql-gateway` | Lightweight API aggregation when upstream URLs are stable |
| `frontend` | Static/containerized frontend runtime fits managed container ingress |
| `feature-service` (optional) | Works if managed Redis is available |

---

## Components that usually stay on Kubernetes first

| Component | Why |
|---|---|
| `graph-service` with self-managed graph | Stateful graph lifecycle often needs stronger ops controls |
| `event-ingest` + `analytics-sink` at scale | Throughput tuning and queue/analytics coupling are easier on K8s |
| optional external **calibration** (URL-driven) and `location-service` | Local `/data` patterns on some services need externalization before elastic autoscaling |
| `investigation-agent` at high scale | Embedded/local stores should be redesigned for highly elastic multi-replica operation |

---

## Suggested progression

1. Start with `core` on managed runtime + managed Postgres/Redis.
2. Add `case-api` and `integration-ingress` once API integrations stabilize.
3. Move to Kubernetes reference deployment when graph, streaming, analytics, or high-scale investigation workflows are needed.

---

## Hard limits to document with customers

- Managed-container path is an **adoption mode**, not the canonical full-scale reference.
- Streaming and analytics SLOs depend on external queue and warehouse architecture.
- Local-disk service variants should not be scaled horizontally without storage redesign.
- Teams should define migration checkpoints from lighter runtime to Kubernetes by throughput or complexity thresholds.
