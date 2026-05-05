# SOC 2 Type II and PCI DSS — Technical control mapping suite

## Purpose and audience

The present suite documents **how designated technical mechanisms** in the Tarka codebase and deployment patterns **relate to** selected **AICPA Trust Services Criteria (TSC)** commonly examined under **SOC 2 Type II** engagements, and to **PCI DSS v4.0** requirements where **cardholder data environment (CDE)** or **connected-to** systems are in scope. The tone and structure are suitable for **enterprise information security**, **risk management**, and **external audit** workpapers.

## Suite contents

| Seq. | Document |
|------|----------|
| 0 | [Executive summary, scope, and limitations](./00-executive-summary-scope-limitations.md) |
| 1 | [Fail-closed data and analytics architecture](./01-fail-closed-database-architecture.md) |
| 2 | [Pre-socket data residency enforcement](./02-pre-socket-residency-controls.md) |
| 3 | [Immutable and tamper-evident audit records](./03-immutable-audit-logs.md) |
| A | [Appendix — Control mapping matrix](./Appendix-A-control-mapping-matrix.md) |

## Reading order

Personnel conducting **readiness assessments** should begin with **Document 0**, review **Documents 1–3** for system description alignment, and conclude with **Appendix A** for the consolidated **control-to-artifact** traceability required in SOC 2 and PCI DSS evidence packages.
