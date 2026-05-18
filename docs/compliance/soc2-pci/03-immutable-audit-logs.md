# Document 3 — Immutable audit logs and tamper-evident decision records

## 3.1 Control objective (narrative)

The entity maintains **audit trails** suitable for **detection**, **investigation**, and **accountability** with respect to **security-relevant** and **compliance-relevant** events. Certain logs are **append-only** by construction; decision records additionally employ **hash chaining** to support **tamper-evident** verification within the constraints of the storage medium.

## 3.2 System description (technical)

### 3.2.1 Canonical decision log (JSON Lines)

The decision service emits **canonical** decision records under schema identifier **`tarka.decision_log/v1`**. Each record includes, inter alia, **`trace_id`**, tenant and entity identifiers, **decision outcome**, scoring inputs, **`fallback_reason`** where degraded paths apply, **`payload_snapshot`** (subject to redaction policy), and **`artifact_manifest`** metadata.

**Immutability model:** Records are **appended** to a **JSON Lines** file (`DECISION_LOG_PATH`). The writer computes **`record_hash`** (SHA-256 over a canonical JSON serialization) and, when a prior record exists, **`previous_record_hash`**, forming a **hash chain** across successive lines.

**Reference implementation:** `services/decision-api/src/decision_api/decision_log.py`; narrative guide: `docs/docs/guides/immutable-decision-records.md`.

### 3.2.2 Sensitive field redaction

Prior to persistence, the writer applies **recursive redaction** for configured sensitive key patterns (e.g., tokens, secrets), reducing **inadvertent** storage of credentials within audit payloads.

**Reference:** `_redact_sensitive` in `services/decision-api/src/decision_api/decision_log.py`.

### 3.2.3 Optional warehouse dual-write

Where **`DECISION_LOG_WAREHOUSE_URL`** is configured, records may be **replicated** to an organization-operated **warehouse ingress** endpoint for **centralized** retention, **immutable** table semantics (organization-defined), and **SIEM** correlation.

### 3.2.4 Relational audit tables (examples)

- **Decision audit** rows persist structured decision attributes for relational query and reporting (`services/decision-api/src/decision_api/models.py`, table **`decision_audit`**).
- **SAR intent state machine** transitions are recorded in **`sar_audit_log`**, documented in code as an **immutable append-only** compliance trail (`services/case-api/src/case_api/models.py`).

### 3.2.5 Rule governance append-only log

Rule-pack mutations may be recorded via **append-only** JSON lines to a lightweight **change log** path for **governance** traceability (`services/decision-api/src/decision_api/rule_api.py`).

## 3.3 Evidence artifacts (non-exhaustive)

| Artifact | Description |
|----------|-------------|
| JSONL decision files | Append-only files with `record_hash` / `previous_record_hash` |
| Database extracts | `decision_audit`, `sar_audit_log` rows with timestamps |
| Replay tooling output | Drift and change-rate reports from `scripts/replay/replay_decision_logs.py` |
| Warehouse load records | Organization-defined immutable table loads |

## 3.4 Limitations (cryptographic)

Hash chaining provides **tamper-evident** properties **conditional on** the **integrity** of the **log file** or **warehouse** medium. It does **not**, absent additional controls, substitute for **write-once** storage, **digital signatures**, or **trusted timestamping** where regulatory mandates require those mechanisms.

## 3.5 Cross-reference

Formal mapping to **TSC** and **PCI DSS** requirements appears in [Appendix A — Control mapping matrix](./Appendix-A-control-mapping-matrix.md).
