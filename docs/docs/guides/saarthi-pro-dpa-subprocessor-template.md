# Saarthi Pro — DPA & subprocessor schedule (template)

> **NOT LEGAL ADVICE.** For **counsel** to adapt. Replace bracketed placeholders; remove inapplicable sections. Do not publish without legal and privacy review.

---

## Data processing agreement — outline

**Between** [CUSTOMER_LEGAL_NAME] (“**Customer**”) and [VENDOR_LEGAL_NAME] (“**Vendor**”) effective [DATE].

### 1. Subject matter and duration

Processing relates to: **AI-assisted investigation copilot** services (chat, tool orchestration, optional feedback/review storage as configured). Term aligns with [MSA / order form].

### 2. Roles

- **Customer** is **controller** (or **controller** with Customer’s affiliate as processor—define).
- **Vendor** is **processor** for categories below, unless BYOK-only deployment where Vendor processes **only** operational metadata.

### 3. Categories of personal data (illustrative—customize)

- Analyst identifiers (IDs, email if passed in headers).
- Investigation prompts and **tool payloads** returned from Customer’s systems.
- Optional: feedback and review records if features enabled.
- **Not in scope** if disabled: Customer case PII in **Customer’s** APIs remains under Customer’s control; Vendor’s access is **instructional** via configured endpoints.

### 4. Subprocessors

Vendor maintains a **subprocessor list** (URL or exhibit). Customer receives notice per MSA for new subprocessors. **LLM provider** (OpenAI, Azure OpenAI, Anthropic, etc.) is a subprocessor **when** Customer uses Vendor-default or Vendor-routed inference; **not** a Vendor subprocessor for **pure BYOK** where Customer contracts directly with the model provider.

| Subprocessor | Function | Location |
|--------------|----------|----------|
| [e.g. cloud host] | Compute / storage | [region] |
| [e.g. LLM API] | Inference (if applicable) | [region] |

### 5. Transfers

Standard contractual clauses / adequacy decisions as required for [regions].

### 6. Security

Reference Vendor’s security documentation; align with Customer’s infosec questionnaire.

### 7. Deletion / return

On termination, delete or return Customer data per [X days] except legal hold.

---

## Subprocessor notification — customer email template

> Internal use when adding a subprocessor.

**Subject:** [Vendor] subprocessor update — [name]

We will add **[Subprocessor name]** for **[function]** effective **[date]**. No change to processing purposes. Objections: reply within **[MSA notice period]**. Details: [link to updated list].

---

## Related

- [Residency & VPC deployment](saarthi-pro-residency-vpc-deployment.md)
- [Intended use & data flows](investigation-agent-intended-use-and-data-flows.md)
