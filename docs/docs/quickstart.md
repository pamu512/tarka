# Quickstart

Get Tarka running locally and evaluate your first fraud decision in under 5 minutes.

---

## Prerequisites

| Tool | Minimum Version |
|---|---|
| [Docker](https://docs.docker.com/get-docker/) | 24.0+ |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.20+ (V2, bundled with Docker Desktop) |
| `curl` or any HTTP client | — |

---

## 1. Clone the Repository

```bash
git clone https://github.com/tarka/tarka.git
cd tarka
```

---

## 2. Start the Core Stack

The core profile gives you the Decision API, Redis, and Postgres — everything needed for real-time rule-based scoring.

```bash
cd deploy
docker compose --profile core up -d
```

Wait for Postgres to become healthy (roughly 10 seconds):

```bash
docker compose ps
```

You should see `postgres`, `redis`, and `decision-api` running with `decision-api` on port **8000**.

---

## 3. Start the Full Stack

For graph analytics, ML scoring, case management, and all other services:

```bash
cp .env.example .env    # enables inter-service URLs
docker compose --profile full up -d
```

This starts all services:

| Service | Port | Profile |
|---|---|---|
| Decision API | 8000 | core |
| Graph Service | 8001 | graph |
| Case API | 8002 | cases |
| Integration Ingress | 8003 | integration |
| Feature Service | 8004 | ml |
| ML Scoring | 8005 | ml |
| Investigation Agent | 8006 | agent |
| Event Ingest | 8007 | streaming |
| Analytics Sink | 8008 | analytics |
| GraphQL Gateway | 8010 | gateway |
| Neo4j Browser | 7474 | graph |
| NATS Monitoring | 8222 | streaming |
| ClickHouse HTTP | 8123 | analytics |

---

## 4. Send Your First Event

Evaluate a payment event for a user. This calls the Decision API directly:

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "event_type": "payment",
    "entity_id": "user-42",
    "payload": {
      "amount": 249.99,
      "currency": "USD",
      "merchant": "electronics-store"
    },
    "metadata": {
      "ip": "203.0.113.42"
    }
  }' | python -m json.tool
```

Expected response:

```json
{
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "decision": "allow",
  "score": 10.0,
  "tags": [],
  "rule_hits": [],
  "reasons": [],
  "ml_score": null
}
```

---

## 5. Trigger a High-Risk Event

Send an event that triggers rules — a large amount from a new device with bot signals:

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "event_type": "payment",
    "entity_id": "user-suspicious",
    "payload": {
      "amount": 9500,
      "currency": "USD"
    },
    "device_context": {
      "device_id": "emulator-001",
      "platform": "web",
      "signals": {
        "is_emulator": true,
        "is_bot": true,
        "is_vpn": true,
        "webdriver_detected": true,
        "headless_detected": true
      }
    }
  }' | python -m json.tool
```

Expected response (score will be high enough to deny):

```json
{
  "trace_id": "...",
  "decision": "deny",
  "score": 95.0,
  "tags": ["sdk:emulator", "sdk:bot", "sdk:vpn", "sdk:webdriver", "sdk:headless"],
  "rule_hits": ["sdk_emulator", "sdk_vpn", "sdk_bot", "sdk_webdriver", "sdk_headless"],
  "reasons": [
    "rules:sdk_emulator,sdk_vpn,sdk_bot,sdk_webdriver,sdk_headless",
    "signals:sdk:emulator,sdk:vpn,sdk:bot,sdk:webdriver,sdk:headless"
  ],
  "ml_score": null
}
```

---

## 6. View the Audit Trail

Every decision is stored. Retrieve it by trace ID:

```bash
curl -s http://localhost:8000/v1/audit/<trace_id> | python -m json.tool
```

---

## 7. Create an Investigation Case

If the full stack is running, create a case for the suspicious entity:

```bash
curl -s -X POST http://localhost:8002/v1/cases \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "title": "Suspicious payment from emulator",
    "entity_id": "user-suspicious",
    "trace_id": "trace-qs-001",
    "priority": "high"
  }' | python -m json.tool
```

---

## 8. Query the Investigation Agent

With the investigation agent running (requires `OPENAI_API_KEY` in `.env`):

```bash
curl -s -X POST http://localhost:8006/v1/investigate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "query": "Summarize the risk profile for user-suspicious and check for connected fraud rings"
  }' | python -m json.tool
```

---

## 9. Explore the Frontend

If the Case API is running, open the investigation UI:

```
http://localhost:8002/ui
```

The frontend (port 3000 if built separately) provides:

- **Dashboard** — Real-time decision feed with score distributions
- **Cases** — Investigation queue with filters and SLA tracking
- **Graph Explorer** — Visual entity graph with community highlighting
- **Rules** — Visual rule builder interface
- **Analytics** — Aggregate fraud metrics

---

## Next Steps

- [Architecture Overview](architecture.md) — Understand how all the pieces fit together
- [Rule Authoring Guide](guides/rules.md) — Write custom detection rules
- [Deployment Guide](guides/deployment.md) — Deploy to production with Kubernetes
- [Graph Analysis Guide](guides/graph-analysis.md) — Detect fraud rings with graph analytics
- [API Reference](api-reference.md) — Complete endpoint documentation
