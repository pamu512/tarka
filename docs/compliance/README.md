# Compliance documentation

This directory contains **structured compliance documentation** intended for **internal control design**, **external audit readiness**, and **customer due diligence** questionnaires. The materials describe how selected technical controls implemented in the Tarka platform **support evidence collection** for common **SOC 2® Type II** (Trust Services Criteria) and **PCI DSS** (Payment Card Industry Data Security Standard) **control objectives**. They do **not** constitute an assertion of compliance, a System and Organization Controls (SOC) report, or a Report on Compliance (ROC) for PCI DSS.

## Document tree

| Document | Purpose |
|----------|---------|
| [SOC 2 / PCI DSS mapping suite](./soc2-pci/README.md) | Index, scope, system descriptions, and formal control mapping matrix |

## Interpretation

Auditors and assessors shall treat the mapping matrix as **illustrative**. Final control classification, sampling, and operating effectiveness testing remain the responsibility of the **service organization** (or **entity** under PCI DSS) and its independent assessor.

## Related technical references (repository)

- Operational resilience and dependency posture: `docs/OPERATIONS.md`, `docs/docs/guides/fallback-emergency-runbook.md`
- Immutable decision records (schema and replay): `docs/docs/guides/immutable-decision-records.md`

---

*SOC 2 is a registered trademark of the AICPA. PCI DSS is maintained by the PCI Security Standards Council. Use of these names herein denotes mapping to publicly published criteria only.*
