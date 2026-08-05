# Golden analyst loop

Default lean journey after fraud-desk compose:

1. **Queue** — `/cases` (SLA + queue score)  
2. **Workbench** — CaseDetail: graph snapshot, rules, shadow, evidence  
3. **Disposition** — status → resolved/closed with `trace_id` → auto `y_label` join for calibration  
4. **QA** — `/ops/qa` sample closed cases, agree/disagree  
5. **Calibration** — `/ops/calibration` posture healthy only with real labels  

## Bring-up

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

## Proofs

```bash
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture
python3 scripts/oss/qa_desk_smoke.py
# Live partner (optional): REQUIRE_LIVE_PARTNER_PROOF=1 + vendor keys — see partner-fusion-proof-runbook.md
```
