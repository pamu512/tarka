# Appendix A — Control mapping matrix

## A.1 Introduction

This appendix establishes **traceability** between (a) the **technical themes** described in Documents 1–3 and (b) selected **AICPA Trust Services Criteria (TSC)** applicable to **SOC 2® Type II** examinations and (c) **PCI DSS v4.0** requirements that frequently apply when **system components** process, store, or transmit **account data** or attach to a **cardholder data environment (CDE)**.

**Mapping type** legend:

| Code | Meaning |
|------|---------|
| **D** | **Design** — The technical mechanism **supports** control **design** when implemented and configured in accordance with service organization policies. |
| **O** | **Operating** — **Operating effectiveness** requires **additional** evidence (sampling, change tickets, MRC reviews) not contained in source code alone. |
| **CUEC** | **Complementary User Entity Control** — The mapping assumes **customer** or **user entity** responsibilities (e.g., identity governance, network segmentation). |

**Disclaimer:** Criterion titles are **abbreviated**. The authoritative text is **TSC 2017** (as updated) and **PCI DSS v4.0**. Numeration of PCI DSS **sub-requirements** may be cited at the **parent** requirement level where **workpaper granularity** does not require sub-item decomposition.

---

## A.2 Matrix — Fail-closed database and analytics architecture

| TSC ID | TSC criterion (abbreviated title) | Typical SOC 2 category | Mapping statement | Type |
|--------|-----------------------------------|-------------------------|-------------------|------|
| **CC6.1** | Logical access security software, infrastructure, and architectures over protected information assets | Security | Fail-closed **withholding** of analytics-backed paths reduces the likelihood of **unauthorized** or **unauthenticated** inference against a **failed** datastore. | D, O, CUEC |
| **CC7.1** | Detection and monitoring procedures to identify anomalies affecting security | Security | Startup **health-check failure** surfaces as **detectable** application state (logged warning; client-visible degradation per API contract). | D, O |
| **CC7.2** | System monitoring — components that have a significant effect on security | Security | Operational monitoring of **analytics availability** and **circuit** posture supports identification of **security-relevant** dependency failure. | O, CUEC |
| **A1.2** | Environmental protections, software, data backup processes, recovery infrastructure | Availability | Fail-closed degradation is consistent with **controlled** reduction of functionality rather than **silent** data loss; **RTO/RPO** remain organization-defined. | D, CUEC |
| **PI1.3** | Inputs are complete, accurate, and authorized — processing completeness | Processing Integrity | Evaluation steps that **omit** or **skip** dependent inputs under declared policy preserve **traceable** processing outcomes (e.g., **`fallback_reason`**). | D, O |

| PCI DSS v4 ref | Requirement theme (abbreviated) | Mapping statement | Type |
|----------------|-----------------------------------|-------------------|------|
| **2.2** | System components configured and managed securely | Hardening of **database** and **analytics** endpoints, TLS, and **least privilege** credentials are **CUECs**; application fail-closed behavior **supports** secure default under outage. | CUEC, D |
| **6.2** | Software engineering / secure development | Defensive initialization and **circuit** configuration are **evidence** of secure SDLC practices when tied to **change records**. | O |
| **6.3** | Web applications protected from known attacks | Indirect: **dependency failure** handling reduces **exploitability** of **error-handling** edge cases when paired with **WAF** and **API gateway** (CUECs). | CUEC |
| **10.2** | Audit logs implement **audit trails** for system components | Fail-closed events (warnings, **503** **`reason_code`**) should appear in **security monitoring** logs; mapping is **O** with **SIEM** correlation. | O, CUEC |
| **11.5** | Network intrusions and unexpected file changes detected / addressed | Change detection on **rules**, **binaries**, and **configs** is a **CUEC**; application signals **support** IR **triage**. | CUEC |

---

## A.3 Matrix — Pre-socket residency blocks

| TSC ID | TSC criterion (abbreviated title) | Typical SOC 2 category | Mapping statement | Type |
|--------|-----------------------------------|-------------------------|-------------------|------|
| **CC6.6** | External threats and malicious acts — protections implemented | Security | **Pre-socket** denial reduces **exfiltration** risk to **disallowed** jurisdictions or vendors prior to transport. | D, O |
| **CC6.7** | Transmission, movement, and removal of information — restricted | Security | **Administrative** matrix blocks and **residency assertions** **restrict** movement of information to **unauthorized** third-party **regions** or **processors**. | D, O, CUEC |
| **CC6.8** | Malicious software — detection, remediation | Security | Indirect: outbound **control** reduces **unintended** data exposure to **unapproved** SaaS; not a substitute for **endpoint** anti-malware. | CUEC |
| **C1.1** | Confidential information identified and maintained | Confidentiality | Residency enforcement supports **confidentiality commitments** regarding **location** of processing. | D, O, CUEC |
| **C1.2** | Confidential information disposed of securely | Confidentiality | Indirect: prevents **initiation** of transfers that would violate **retention** or **cross-border** contracts. | D, CUEC |
| **P1.1** | Privacy notice communicated (if privacy category in scope) | Privacy | When **personal information** is subject to **geographic** restrictions, pre-socket blocks **support** notice commitments **if** such commitments exist. | D, CUEC |

| PCI DSS v4 ref | Requirement theme (abbreviated) | Mapping statement | Type |
|----------------|-----------------------------------|-------------------|------|
| **1.2.5** | Traffic between CHD environment and other networks restricted | Where ingress is **CDE-adjacent**, residency blocks **support** **scope** and **egress** restrictions; **network ACLs** remain **CUECs**. | CUEC, D |
| **1.3.1** | Network security controls (NSCs) defined / implemented | Same as above; **defense in depth** with **application-layer** enforcement. | CUEC, D |
| **3.3.1** | PAN storage limited | Residency blocks do **not** directly enforce PAN minimization; **supporting** control when **OSINT** could otherwise retrieve **PAN-bearing** third-party responses (**policy-dependent**). | CUEC |
| **4.2.1** | Strong cryptography for PAN transmission over OUN | Pre-socket block occurs **before** transmission; **cryptography** for **permitted** flows remains **CUEC** (TLS termination, HSTS). | CUEC, D |
| **12.8** | Third-party service provider (TPSP) management | Vendor **classification** and **matrix** governance evidence **due diligence** over **TPSPs** when documented. | O, CUEC |

---

## A.4 Matrix — Immutable audit logs and tamper-evident decision records

| TSC ID | TSC criterion (abbreviated title) | Typical SOC 2 category | Mapping statement | Type |
|--------|-----------------------------------|-------------------------|-------------------|------|
| **CC7.1** | Detection and monitoring — anomalies | Security | Append-only **decision** and **compliance** logs increase **detectability** of **unauthorized** or **anomalous** activity when reviewed. | D, O |
| **CC7.2** | System monitoring | Security | **JSONL** and **relational** audit tables feed **monitoring** and **SIEM** use cases (organization-defined). | O, CUEC |
| **CC7.3** | Security events evaluated | Security | **Replay** and **hash chain** verification procedures **support** **forensic** evaluation. | D, O |
| **CC7.4** | Anomalies resolved | Security | Audit artifacts underpin **incident** **closure** workpapers when tied to **IR** procedures. | O |
| **CC4.1** | Monitoring activities — assessments | Security / COSO | **Drift** and **replay** outputs **support** **ongoing** assessments of **processing** vs. **baseline**. | O |
| **PI1.4** | Processing activities recorded completely and accurately | Processing Integrity | **Canonical** schema, **hash** linkage, and **`fallback_reason`** fields **support** **complete** documentation of **processing** outcomes. | D, O |
| **PI1.5** | Processing activities recorded completely and accurately — inputs and outputs | Processing Integrity | **`payload_snapshot`** (subject to redaction) and **`inference_context`** **support** **reconstruction** of inputs/outputs. | D, O, CUEC |

| PCI DSS v4 ref | Requirement theme (abbreviated) | Mapping statement | Type |
|----------------|-----------------------------------|-------------------|------|
| **10.2.1** | **Audit logs** capture **required** events for **system components** | Decision and residency compliance logs **contribute** to **event** capture where those components are **in scope**. | D, O |
| **10.2.1.1** | **Audit logs** capture **required** events (additional detail per v4) | Organization shall map **specific** PCI **event types** to log fields (**custom** column mapping). | O, CUEC |
| **10.3** | **Audit logs** detail **required** data fields | **`trace_id`**, timestamps, and actor/tenant fields **partially** satisfy; **full** PCI field set requires **configuration** review. | O, CUEC |
| **10.4** | Time synchronization | **NTP** on hosts is a **CUEC**; application emits **ISO 8601** timestamps in **UTC**. | CUEC, D |
| **10.5** | **Audit logs** protected from destruction / tampering | **Append-only** files and **hash chaining** **support** **integrity**; **OS** and **bucket** **immutability** are **CUECs**. | D, O, CUEC |
| **10.6** | **Audit logs** reviewed | **Manual** or **automated** review is **CUEC**; tooling (**replay**) **supports** **analytics** of anomalies. | O, CUEC |
| **10.7** | **Audit log** history retained per **PCI** policy | Retention in **JSONL**, **database**, or **warehouse** is **organization-defined**. | CUEC, O |

---

## A.5 Consolidated summary (management view)

| Architecture theme | Primary TSC clusters | Primary PCI DSS v4 clusters |
|--------------------|---------------------|-----------------------------|
| Fail-closed database / analytics | **CC6**, **CC7**, **PI1**, **A1** (as applicable) | **2**, **6**, **10**, **11** (supporting) |
| Pre-socket residency | **CC6**, **C1**, **P1** (if privacy in scope) | **1**, **3**, **4**, **12** (supporting / scoping) |
| Immutable / tamper-evident audit | **CC4**, **CC7**, **PI1** | **10** (primary), **5** (when FIM correlated) |

---

## A.6 Document approval (template)

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Information Security Officer | | | |
| Engineering Lead | | | |
| Compliance / GRC | | | |
