# Warehouse sink v1

Tarka emits receipt + label export. **The buyer owns the lake.** Tarka does not host Snowflake/BigQuery.

Join key = `evaluation_token` (see [label-join-v1](label-join-v1.md)).

Export: `GET /v1/exports/receipts?tenant_id=&from=&to=` → JSON receipts + label maps + `training_rows`.

Empty object/file sink = local only.

Example SQL (EXAMPLE, buyer warehouse):

```sql
-- EXAMPLE
SELECT r.evaluation_token, r.tenant_id, r.entity_id, r.action, l.label_kind
FROM receipts r
JOIN labels l ON l.evaluation_token = r.evaluation_token;
```
