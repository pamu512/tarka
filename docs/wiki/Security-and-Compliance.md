# Security and Compliance

- Responsible disclosure: [`SECURITY.md`](https://github.com/pamu512/tarka/blob/master/SECURITY.md)
- Dependency / Neo4j AGPL notes: [`LICENSE-DEPENDENCIES.md`](https://github.com/pamu512/tarka/blob/master/LICENSE-DEPENDENCIES.md)
- Fail-closed DB / audit posture: `docs/compliance/soc2-pci/` (control narrative; not a certification claim)
- Claim hygiene: [`docs/compliance/CLAIM_LOCK.md`](https://github.com/pamu512/tarka/blob/master/docs/compliance/CLAIM_LOCK.md)
- Scanning: [`docs/docs/guides/security-scanning.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/security-scanning.md)
- Decision accountability export: PROV-O via `scripts/compliance/export_decision_prov.py` (see [Decision accountability graph](Decision-Accountability-Graph))

Tarka defaults to **local-first Shadow** so agentic reasoning need not export PII to a vendor LLM. Production mocks are forbidden; desk-strict includes trend ops surfaces.
