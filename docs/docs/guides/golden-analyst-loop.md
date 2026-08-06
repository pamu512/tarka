# Golden analyst loop

Default lean Day-1 journey after the fraud-desk compose profile. This is the
product path the missed-mark bridge optimizes for — not the full hardware triad
and not brochure mocks.

## Path

1. **Queue** — `/cases`  
   Queue score sort; SLA clocks by priority (`sla_breached_by_priority`); filter
   a priority to see that queue’s breach count.
2. **Workbench** — `/cases/:id`  
   Graph snapshot, rule hits, shadow metadata, evidence bundle, copilot rail.
3. **Disposition** — terminal status + **reason-code enum** (required)  
   - Legit reasons (`FALSE_POSITIVE`, `CUSTOMER_CLEARED`, …) apply and join
     `y_label` immediately.  
   - Fraud reasons escalate to `resolved_fraud` / `sar_filed` and **park for
     maker-checker** until a distinct second actor approves.
4. **QA** — `/ops/qa`  
   Sample closed cases → pending queue → agree/disagree → agreement metrics.
5. **Calibration / rules** — `/ops/calibration` + Rule performance  
   Posture healthy only with real labels; “After dispositions” panel shows
   precision / FP proxy per `rule_id`.

Optional action layer: `recommended_action` → challenge / step-up — see
[decision-to-customer-journey.md](./decision-to-customer-journey.md).

False-positive / support handoff: [false-positive-support-kit.md](./false-positive-support-kit.md)
(CaseDetail → **Copy support-safe summary**).

## Bring-up

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

Front door: README “Start here” and
[oss-15-minute-first-decision.md](./oss-15-minute-first-decision.md).

Desk mocks stay off by default (`VITE_DESK_STRICT`); only
`VITE_USE_API_MOCKS=true` re-enables desk mock fallback.

## Proofs

```bash
# Hybrid partner fusion (fixture — release checklist)
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture
# Pin: docs/compliance/partner-fusion-proof.stable.sha256
#      3d1ab910a52dbad2c5ecddcf46b653fbe57966cc9fd5461a1cdc100676a30b88

python3 scripts/oss/qa_desk_smoke.py
python3 scripts/oss/sar_transport_honesty_smoke.py
python3 scripts/audit_stubs.py
python3 scripts/audit_prod_desk_mocks.py

# Mock-free QA Playwright (manual until a CI job exists)
./scripts/e2e/reset-micro-for-playwright.sh
cd frontend && E2E_QA_DESK=1 npx playwright test e2e/ops-qa-desk.spec.ts

# Live partner (optional, not hybrid-bar blocking):
# REQUIRE_LIVE_PARTNER_PROOF=1 + vendor keys — partner-fusion-proof-runbook.md
```

## Related

| Doc | Role |
|-----|------|
| [partner-enrichment-fusion.md](./partner-enrichment-fusion.md) | Hybrid device/location contract |
| [shadow-and-ab-testing.md](./shadow-and-ab-testing.md) | `metadata.shadow` evaluate path |
| [calibration-ops-runbook.md](./calibration-ops-runbook.md) | Reliability / posture ops |
| [competitive-score-matrix-2026-04.md](./competitive-score-matrix-2026-04.md) | Hybrid 4.2 scores + bridge footnotes |
| Bridge plan | `docs/superpowers/plans/2026-08-05-missed-mark-bridge.md` |
