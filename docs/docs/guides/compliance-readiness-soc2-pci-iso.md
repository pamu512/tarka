# Compliance readiness: SOC 2, PCI DSS, ISO 27001

Short orientation for teams deploying **self-hosted** Tarka (or similar stacks). This repository **does not** provide SOC 2, PCI, or ISO **certificates** — **your organization** and **your environment** are assessed. Use this page to align engineering and GRC on **readiness** vs **attestation**.

---

## Readiness vs certified

| Term | Meaning |
|------|---------|
| **Ready** | Gap analysis done, controls implemented, policies and **evidence** exist (tickets, logs, access reviews). You could start an external audit. |
| **Certified / in scope** | A **qualified assessor** attests that defined criteria are met for a **stated scope** and period (SOC 2 / ISO) or PCI validation path (SAQ, ROC, etc.). |

Deploying OSS does not transfer compliance; **you** operate the controls on your cloud account, networks, and processes.

---

## SOC 2 (AICPA Trust Services Criteria)

- **Typical buyers want** SOC 2 **Type II** (controls operating effectively over months), sometimes preceded by **Type I** (point-in-time).
- **Who:** CPA firms licensed for SOC engagements.
- **Path (simplified):** define scope (often Security + Confidentiality) → map controls to TSC → implement (access, change management, logging, vendors, incidents) → collect evidence → readiness review → Type I and/or Type II audit.
- **Self-hosted Tarka:** infrastructure, IAM, patching, backups, encryption, monitoring are **your** controls; document **subprocessors** (cloud provider, IdP, optional LLM vendor for the investigation agent, etc.).

---

## PCI DSS

- **Applies** when you **store, process, or transmit** **cardholder data** (PAN, sensitive authentication data) in systems in scope.
- **First step:** **narrow scope** — avoid storing PAN; use processor tokens where possible; define the **CDE** (cardholder data environment) clearly.
- **Path:** SAQ for smaller / simpler scopes; **QSA** and **ROC** when required. Controls cover segmentation, MFA, vulnerability management, logging, encryption, secure SDLC (see current PCI DSS version from the PCI SSC).
- **Tarka:** confirm whether **any** service receives or logs PAN. If the stack only handles **tokens, entity IDs, and behavioral signals**, PCI scope may be limited — **architecture and legal** must confirm; do not assume.

---

## ISO / IEC 27001

- **Who:** Accredited **certification bodies** (not CPAs).
- **Core:** an **ISMS** — scoped assets, risk assessment, **Statement of Applicability** (Annex A controls), policies, internal audit, management review → Stage 1 / Stage 2 audits → ongoing surveillance.
- **Overlap:** Many security controls overlap with SOC 2; a **single control matrix** reduces duplicate work.

---

## Practical sequence (all frameworks)

1. **Scope** — products, regions, environments, and **data types** (especially whether **card data** exists).
2. **Data flows & subprocessors** — diagrams including Tarka services, databases, Redis, streaming, optional LLM usage ([LLM data flows](./investigation-agent-llm-data-flow.md)).
3. **Control matrix** — requirement → owner → evidence → tool (IdP, SIEM, ticketing).
4. **Foundations** — identity (SSO/MFA), secrets management, encryption in transit and at rest, logging and retention, backups and DR, patching, vulnerability management, incident response.
5. **Internal audit** → external SOC 2 / ISO; **PCI** per QSA or SAQ path.

---

## Related

- [Regulated markets feature pack](./feature-pack-regulated-markets.md)  
- [Investigation agent — LLM data flows](./investigation-agent-llm-data-flow.md)  
- [Security scanning](./security-scanning.md)

---

## Disclaimer

This guide is **not** legal or compliance advice. Engage qualified **auditors**, **QSAs**, and counsel for your jurisdiction and contractual obligations.
