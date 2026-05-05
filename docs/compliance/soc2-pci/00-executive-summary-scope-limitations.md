# Document 0 — Executive summary, scope, and limitations

## 0.1 Executive summary

The Tarka platform incorporates **defense-in-depth** measures across **persistence**, **egress**, and **audit** planes. Three architectural themes are documented herein because they recur in **SOC 2 Type II** examinations (Security, Availability, Confidentiality, and Processing Integrity categories, as applicable) and in **PCI DSS** assessments where **logging**, **access to system components**, and **protection of cardholder data** (including **scope reduction** via technical enforcement) are material:

1. **Fail-closed database and analytics posture** — Dependent subsystems that materially affect **security-relevant** or **integrity-relevant** outcomes are not permitted to present a **false “available”** state when prerequisites are not satisfied; analytic query paths may be **withheld** when backing stores fail health validation.
2. **Pre-socket residency blocks** — Certain **cross-border** or **policy-denied** data flows are **interdicted prior to establishment of outbound transport** (i.e., before application-layer HTTP clients complete connection setup for disallowed vendors), with **compliance audit records** generated at the point of denial.
3. **Immutable audit logs** — Selected audit artifacts are **append-only** by design (e.g., **JSON Lines** decision logs with **cryptographic hash chaining**, **relational** append-only SAR state-transition logs), supporting **detective** control objectives and **non-repudiation** where the service organization’s policies so prescribe.

## 0.2 Scope

### 0.2.1 In scope (technical)

- Application services and shared libraries within this repository that implement or enforce the mechanisms described in Documents 1–3.
- Configuration surfaces (environment variables, deployment manifests) that **govern** activation of logging, warehouse dual-write, and residency policy.

### 0.2.2 Out of scope (explicit)

- **Operating effectiveness** of controls over a defined review period (SOC 2 Type II).
- **Physical and environmental** controls, **HR background checks**, **vendor SOC** reliance, and **key management** outside the application boundary, except where referenced as **complementary user entity controls (CUECs)** or **organization-defined parameters**.
- **PCI DSS** scoping decisions (CDE segmentation, network diagrams, PAN flows). The mapping matrix identifies **candidate** PCI requirements only where technical artifacts may **support** evidence; it does **not** assert that any deployment processes cardholder data.

## 0.3 Limitations and professional judgment

This documentation is **not** a substitute for:

- A **SOC 2** examination report issued under **AT-C section 205** (or successor attestation standards), or  
- A **PCI DSS** **Report on Compliance** or **Self-Assessment Questionnaire** completed by a **Qualified Security Assessor** or **Internal Security Assessor**, as applicable.

Control **design suitability** and **operating effectiveness** shall be determined by the **service organization** in consultation with its **independent auditor** or **assessor**. Terminology herein aligns with **COSO**-based TSC interpretation practices commonly applied in **Big Four** and **specialized boutique** SOC engagements; **minor variance** in criterion numbering or naming may occur across audit firm methodology guides.

## 0.4 Document control

| Field | Value |
|-------|--------|
| Classification | Internal — Customer-shared excerpts permitted under NDA |
| Owner | Information Security / Engineering (joint) |
| Review cadence | Annual, or upon material architecture change |
