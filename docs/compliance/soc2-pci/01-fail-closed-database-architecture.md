# Document 1 — Fail-closed database and analytics architecture

## 1.1 Control objective (narrative)

The entity restricts **logical and analytical processing** such that **material dependencies** on **databases** and **analytical stores** do not yield **silent omission** of security- or integrity-relevant behavior. Where health validation or access preconditions are not met, the system shall **fail closed** with respect to the affected capability (i.e., **withhold** or **deny** the capability rather than proceed with **unauthenticated** or **unverified** access assumptions).

## 1.2 System description (technical)

### 1.2.1 Analytical datastore initialization

The decision service performs **startup validation** of the configured **ClickHouse** (or substitute analytics engine) client. Upon **failure** of the bounded health probe, the implementation **disassociates** the analytics client from application state and records a **warning** indicating that dependent routes will operate in a **fail-closed** manner with respect to analytics-backed execution paths.

**Design intent:** Analytic query surfaces that require a **trusted** analytics substrate shall not execute against an **unverified** or **failed** connection.

**Reference implementation:** `services/decision-api/src/decision_api/deps.py` (`open_analytics_infra`).

### 1.2.2 Operational dependency and circuit posture

The platform maintains **documented** dependency resilience policies (timeouts, retry bounds, circuit thresholds) for evaluation steps that may invoke **external** or **shared** subsystems. Degraded modes are **explicitly** surfaced (for example, via **`fallback_reason`** and **`step_trace`** semantics) rather than implied as nominal success paths.

**Reference materials:** `services/decision-api/src/decision_api/config.py` (`dependency_resilience_policy_table`), `docs/docs/guides/fallback-emergency-runbook.md`, `docs/OPERATIONS.md`.

### 1.2.3 API contract under partial outage

Client integrations are instructed to treat **HTTP 503** responses carrying **`reason_code`** as **first-class** signals of **dependency outage**, consistent with a **fail-closed** operational contract at the **service boundary**.

**Reference:** `docs/OPERATIONS.md`.

## 1.3 Evidence artifacts (non-exhaustive)

| Artifact | Description |
|----------|-------------|
| Application logs | Startup warnings referencing analytics health-check failure |
| Configuration records | ClickHouse host, credentials provisioning, TLS parameters (organization-defined) |
| Runbooks | Declared degraded and containment modes |
| Automated tests | Resilience and chaos smoke workflows where implemented |

## 1.4 Complementary user entity controls (CUECs)

The service organization shall:

- Provision **network policies** and **credential rotation** appropriate to **least privilege** for database and analytics connectivity.
- Monitor **availability** and **latency** SLOs for persistence tiers and **declare** incident response procedures when **fail-closed** paths elevate **transactional** impact.

## 1.5 Cross-reference

Formal mapping to **TSC** and **PCI DSS** requirements appears in [Appendix A — Control mapping matrix](./Appendix-A-control-mapping-matrix.md).
