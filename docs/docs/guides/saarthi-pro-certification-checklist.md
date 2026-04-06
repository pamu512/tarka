# Saarthi Pro — certification checklist (Bronze / Silver / Sustained)

> **Internal.** Execute during onboarding or quarterly re-certification. Evidence: screenshots, CI logs, or signed customer attestation stored in **your** CRM or ticket.

## Bronze — Conformance smoke

**Audience:** Runtime + support; customer-built adapter.

- [ ] Deployed agent returns **`contract_version`** on `GET /v1/integration` (or health `integration`).
- [ ] `python scripts/ci/check_integration_contract.py --base-url <URL>` exits 0 (with `--api-key` if required).
- [ ] `INTEGRATION_PROFILE_ID` set and recorded in [adapter catalog](saarthi-pro-adapter-catalog-and-certification.md) (customer row).
- [ ] Analyst can complete **one** golden-path chat (case lookup or safe read-only tool) in UAT.

**Sign-off:** Customer SME + Saarthi support owner (names, date).

## Silver — Conformance golden

**Audience:** Certified adapter tier.

- [ ] All **Bronze** items.
- [ ] Agreed **golden profiles** (e.g. `full`, `no_graph`) exercised in **customer UAT** or Pro staging with customer API mocks; pytest or scripted equivalent green (link to log).
- [ ] Adapter version (or image digest) recorded next to profile row in adapter catalog.
- [ ] [Customer API change policy](saarthi-customer-api-change-policy.md) acknowledged by customer technical owner.

**Sign-off:** Customer integration lead + Pro engineering lead.

## Sustained — Operational certification

**Audience:** Adapter + SLA tier.

- [ ] All **Silver** items.
- [ ] Quarterly (or contract-defined) re-run of Silver checks **or** customer CI job calling smoke + one golden profile.
- [ ] Support channel and **severity** tier documented ([support severity](saarthi-pro-support-severity.md)).
- [ ] Incident runbook exchanged ([managed operations runbook](saarthi-pro-managed-operations-runbook.md)).

**Sign-off:** Customer ops manager + Pro customer success (annual or per renewal).

## Related

- [Adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md)
- [Upgrade from OSS](saarthi-pro-upgrade-from-oss.md)
