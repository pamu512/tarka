# Quickstart

Clone → one command → seeded suspicious event → decision → audit → case → UI.

---

## Prerequisites

| Tool | Minimum |
|---|---|
| [Docker](https://docs.docker.com/get-docker/) | 24.0+ |
| [Docker Compose](https://docs.docker.com/compose/install/) V2 | 2.20+ |
| `curl` | — |

---

## 1. Clone

```bash
git clone https://github.com/pamu512/tarka.git
cd tarka
```

---

## 2. Start the OSS lite stack (one command)

```bash
ALLOW_INSECURE_NO_AUTH=true TENANT_BINDING_REQUIRED=false docker compose -f infra/deploy/docker-compose.lite.yml up --build -d
```

This starts Postgres, Redis, **core-api** (decisions + cases on **:8000**), signal-api, integration-ingress, and the analyst UI.

Wait until healthy:

```bash
curl -sf http://127.0.0.1:8000/v1/health
curl -sf http://127.0.0.1:8000/decisions/v1/health
```

Optional graph profile (Neo4j/Gremlin + graph-service):

```bash
ALLOW_INSECURE_NO_AUTH=true TENANT_BINDING_REQUIRED=false docker compose -f infra/deploy/docker-compose.lite.yml --profile graph up --build -d
```

Local LLM / Shadow is an **advanced add-on**, not required for this path (see `infra/deploy/local-ai/`).

---

## 3. Seed a suspicious event → decision

```bash
curl -s -X POST http://127.0.0.1:8000/decisions/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "event_type": "payment",
    "entity_id": "user-suspicious",
    "payload": {
      "amount": 9500,
      "currency": "USD",
      "merchant": "electronics-store"
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
  }' | tee /tmp/tarka-decision.json
```

Note `trace_id` from the JSON response.

---

## 4. Audit lookup

```bash
TRACE_ID=$(python3 -c "import json; print(json.load(open('/tmp/tarka-decision.json'))['trace_id'])")
curl -s "http://127.0.0.1:8000/decisions/v1/audit/${TRACE_ID}" | python3 -m json.tool
```

The audit `payload_snapshot.decision_evidence` includes the point-in-time feature map and `rule_pack_content_sha256`.

---

## 5. Open a case

```bash
curl -s -X POST http://127.0.0.1:8000/cases/v1/cases \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"demo\",
    \"title\": \"Suspicious payment from emulator\",
    \"entity_id\": \"user-suspicious\",
    \"trace_id\": \"${TRACE_ID}\",
    \"priority\": \"high\"
  }" | python3 -m json.tool
```

---

## 6. Analyst UI

Open the Vite console (compose maps it; commonly **http://127.0.0.1:3000**):

- **Cases** → open the case
- **Investigation** → evidence-grounded copilot (rules remain authoritative)
- **Rules / Simulation / Audit / Integrations / Help**

---

## Production notes

- Outside demo mode, set `API_KEYS` **and** `API_KEY_TENANT_MAP` (wildcard tenant scopes are not default).
- Prefer `ALLOW_INSECURE_NO_AUTH=false` with real keys.
- Helm prod requires persistent Postgres (or external DB) and a non-default password.

## Next steps

- [Architecture](architecture.md)
- [Rule authoring](guides/rules.md)
- [Deployment](guides/deployment.md)
- [Python SDK](sdks/python.md) · [TypeScript SDK](sdks/typescript.md)
