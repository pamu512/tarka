# Saarthi Pro — managed operations & incident runbook (internal)

> **Internal.** Customize per deployment (Customer VPC vs Vendor-managed). Pair with [support severity](saarthi-pro-support-severity.md).

## Roles

| Role | Responsibility |
|------|------------------|
| Customer ops | Uptime of Customer APIs, IdP, network paths |
| Pro support / SRE | Agent runtime, adapter (if maintained), release coordination |
| Security | CVE triage, breach process |

## Routine operations

- **Upgrades:** follow [upgrade from OSS](saarthi-pro-upgrade-from-oss.md) and Pro **release notes**; blue/green or canary recommended.
- **Backups:** SQLite stores (feedback, review, knowledge) — snapshot volumes or export per Customer RPO; document paths from `INVESTIGATION_DATA_DIR` / `COPILOT_*_DB_NAME`.
- **Certificates:** renew gateway and agent TLS before expiry; automate where possible.
- **Capacity:** watch LLM token rate, agent CPU, upstream case API latency; scale replicas behind load balancer.

## Incident response (outline)

1. **Detect:** monitoring alert, customer report, or security scan.
2. **Triage:** assign P1–P4; for P1 open bridge with customer if SLA requires.
3. **Contain:** scale to zero, block API key, revoke gateway rule—least invasive first.
4. **Eradicate:** patch version, config fix, adapter hotfix.
5. **Recover:** verify `check_integration_contract.py`, sample chat, stream path.
6. **Post-incident:** blameless notes; update runbook; if P1, executive summary per MSA.

## Security-specific

- Suspected **credential leak:** rotate `API_KEYS`, upstream keys, LLM keys; review audit logs for abuse window.
- **CVE in base image:** rebuild Pro image; publish advisory in release notes; CVSS-driven priority.

## Contacts (fill per program)

- Support email / portal: [ ]
- Escalation phone: [ ]
- Security: [ ]

## Related

- [Residency & VPC](saarthi-pro-residency-vpc-deployment.md)
- [Assurance & liability positioning](saarthi-pro-assurance-liability-positioning.md)
