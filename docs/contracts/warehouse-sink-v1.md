# Warehouse sink v1

Tarka emits receipt + label export. **The buyer owns the lake.** Tarka does not host Snowflake/BigQuery.

Join key = `evaluation_token` (see [label-join-v1](label-join-v1.md)). Required on every export row: `evaluation_token`, `trace_id`, `tenant_id`, `entity_id`. Optional party ids are copied from the event when present — never invented.

Export: `GET /v1/exports/receipts?tenant_id=&from=&to=` → JSON receipts + label maps + `training_rows`.

Empty object/file sink = local only.

## Scheduled consume (buyer-owned)

Tarka export → buyer lake → optional re-ingest of **label facts** only. Tarka does not run the warehouse job, host the lake, or open a case CRM inbox. Labels never Auto-Promote.

| Item | Contract |
|------|----------|
| Owner | Buyer scheduler (cron / Airflow / warehouse task). Not a Tarka-hosted worker. |
| Schedule | Buyer-chosen. EXAMPLE daily window is enough; late labels may arrive 30–120 days later so re-pull the same join keys. |
| Pull | `GET /v1/exports/receipts?tenant_id=&from=&to=` (analyst role). |
| Join | `receipts.evaluation_token = labels.evaluation_token` (fallback `trace_id` + `tenant_id`). |
| Idempotency | Upsert on `tenant_id \| from \| to \| evaluation_token`. Same window + token = one lake row. Do not append duplicates. |
| Re-ingest | Optional: buyer may POST label facts back via `POST /v1/webhooks/late-label`. Bind only — no feature rebuild, no CRM case, no Auto-Promote. |
| Observe drafts | Optional: joined labels since T may propose Observe / shadow drafts. Never auto Active. Not a case inbox. |
| Not this | Case CRM inbox; Tarka-hosted Snowflake/BigQuery; chargeback-guarantee SKU; Auto-Promote from labels. |

EXAMPLE cron (buyer host, not shipped as a Tarka service):

```
# EXAMPLE — buyer lake. Tarka does not host this job.
15 2 * * * curl -fsS -H "Authorization: Bearer $TARKA_ANALYST_TOKEN" \
  "$TARKA_DECISION_URL/v1/exports/receipts?tenant_id=$TENANT&from=$(date -u -d 'yesterday' +%Y-%m-%dT00:00:00Z)&to=$(date -u +%Y-%m-%dT00:00:00Z)" \
  | lake_upsert --idempotency-key tenant,from,to,evaluation_token
```

See [bakeoff-sop](../docs/guides/bakeoff-sop.md) for the Observe-week pointer.

Example SQL (EXAMPLE, buyer warehouse):

```sql
-- EXAMPLE
SELECT r.evaluation_token, r.tenant_id, r.entity_id, r.action, l.label_kind
FROM receipts r
JOIN labels l ON l.evaluation_token = r.evaluation_token;
```

## Optional Observe draft mint

Joined warehouse labels since T may propose Observe drafts only (`decision_api.label_observe_job.consume_joined_labels`, `authored_by=seed`). Same buyer-owned optional job — empty input mints nothing. Promote only via existing gates / human. Never auto Active. Not a case inbox.
