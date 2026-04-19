# Calibration exports

## Reliability dataset (CSV)

`export_reliability_dataset.py` reads **`decision_audit`** via `DATABASE_URL` and writes a CSV with score, decision, `inference_context` fields (integrity, tier, calibration profile), and an empty **`y_label`** column for you to join with labels from case-api / warehouse.

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/fraud
python scripts/calibration/export_reliability_dataset.py \
  --out /tmp/reliability.csv --tenant-id acme --limit 10000
```

Use the CSV in a notebook or BI tool for **reliability curves** (bin by `score` or `integrity_confidence` vs outcomes once labels are joined).

See also: `services/decision-api` **`POST /v1/calibration/snapshots`** and **`GET /v1/ops/calibration-status`**.
