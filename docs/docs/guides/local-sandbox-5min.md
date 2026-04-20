# 5-Minute Local Sandbox

## 1) Start core services

```bash
docker compose -f deploy/docker-compose.lite.yml up -d
```

## 2) Send one evaluate event

```bash
curl -sS http://localhost:8000/v1/decisions/evaluate \
  -H 'content-type: application/json' \
  -H "x-api-key: ${API_KEY:-dev-key}" \
  -d '{
    "tenant_id":"demo",
    "event_type":"payment",
    "entity_id":"acct_demo_1",
    "payload":{"amount":199.0,"currency":"USD"},
    "device_context":{"device_id":"dev_demo_1","platform":"web","signals":{"is_vpn":true}}
  }' | jq .
```

## 3) Inspect inference + evidence

- Open frontend case detail and inspect inference metrics/tags.
- Download evidence bundle from case detail.
- Check decision logs under `./data/decision_logs/decision-log.jsonl`.

## 4) Run parity smoke

```bash
python scripts/replay/export_audit_to_jsonl.py --tenant-id demo --entity-id acct_demo_1
python scripts/replay/replay_aggregates.py --input ./tmp/audit-export.jsonl
python scripts/replay/diff_aggregate_redis.py --online redis://localhost:6379/0 --scratch redis://localhost:6379/15
```
