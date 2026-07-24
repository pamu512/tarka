# Calibration exports

## Reliability dataset (CSV)

**HTTP (preferred):**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/v1/calibration/reliability-export.csv?tenant_id=acme&limit=10000" \
  -o /tmp/reliability.csv
```

**Bins (sketch curve; proxy labels):**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/v1/calibration/reliability-bins?tenant_id=acme&n_bins=10"
```

`proxy_label_from_decision` / bin caveats are **not** ground truth — join case dispositions into `y_label` for true reliability diagrams.

**CLI (same columns, air-gapped):**

`export_reliability_dataset.py` reads **`decision_audit`** via `DATABASE_URL`.

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/fraud
python scripts/calibration/export_reliability_dataset.py \
  --out /tmp/reliability.csv --tenant-id acme --limit 10000
```

See also: `POST /v1/calibration/snapshots` and `GET /v1/ops/calibration-status`.
