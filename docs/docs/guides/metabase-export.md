# Metabase / BI export path (Wave 5)

Tarka does not ship Metabase. Export curated fraud KPIs and wire Metabase (or Grafana) yourself.

## Scorecard JSON

```bash
python scripts/analytics/export_weekly_scorecard_json.py --out /tmp/scorecard.json
# or HTTP when analytics-sink is up:
curl -H "Authorization: Bearer $TOKEN" \
  "$ANALYTICS_SINK/v1/analytics/scorecard?tenant_id=acme" -o /tmp/scorecard.json
```

## Reliability CSV (calibration)

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$DECISION_API/v1/calibration/reliability-export.csv?tenant_id=acme&limit=10000" \
  -o /tmp/reliability.csv
```

## Metabase recipe

1. Create a Metabase database pointing at Postgres (decision_audit) or ClickHouse (analytics sink).
2. For file-based imports: upload `/tmp/scorecard.json` / CSV via Metabase upload or an ETL job into a staging table.
3. Prefer Grafana JSON dashboards under `infra/deploy/observability/grafana/` for ops SLOs; use Metabase for analyst ad-hoc SQL.

Do not rebuild charting inside Tarka when a BI tool already covers the surface.
