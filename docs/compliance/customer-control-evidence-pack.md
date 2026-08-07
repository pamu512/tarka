# Customer control evidence pack

OSS Tarka is **not** a SOC2 Type II vendor attestation. This pack helps **customers** evidence controls they operate when deploying Tarka.

## Contents (map to your DPIA / TSC workbook)

| Control theme | Where in Tarka |
|---------------|----------------|
| Fail-closed decisions | `docs/compliance/soc2-pci/01-fail-closed-database-architecture.md` |
| Audit before response | Architectural pillars; `AuditRecord` / `AuditLog` |
| Replay / forensics | `tarka replay`, counter parity scripts |
| Access control | `auth_rbac`, API keys, tenant binding |
| Encryption / KMS | integration-ingress vault + KMS runbook |
| Change control | rule change-log, policy-check CI, challenge policies |
| Incident / SLO | `docs/docs/operations/slo-burn-response.md` |
| Honesty / stub gate | `scripts/audit_stubs.py`, `docs/STUB_REGISTER.md` |

## Operator checklist

1. Export recent `decision_audit` sample + retention policy.
2. Capture compose/Helm values (no secrets) for the deployment profile.
3. Attach CI green `audit_stubs` + counter-parity artifacts for the release SHA.
4. Document who holds `RULE_GOVERNANCE_SECRET` / challenge webhook secrets.

## Export helper

```bash
python scripts/compliance/export_control_evidence_index.py
```

Writes `artifacts/control-evidence-index.json` listing the paths above.
