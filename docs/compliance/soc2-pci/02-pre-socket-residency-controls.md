# Document 2 — Pre-socket data residency controls

## 2.1 Control objective (narrative)

The entity enforces **data residency** and **cross-border processing** restrictions **prior to** initiation of disallowed **outbound application traffic** to third-party processors. Administrative **denylists** (tenant–vendor **matrix blocks**) and **jurisdictional** policy checks are evaluated **before** the HTTP client stack is permitted to perform transport for the disallowed request.

## 2.2 System description (technical)

### 2.2.1 Administrative pre-socket blocks

The integration ingress component maintains an in-memory **residency matrix** mapping **tenant identifiers** to **vendor keys** that are **administratively blocked**. The block is enforced **pre-socket**: the control path records a **compliance audit** entry and raises a **`DataResidencyViolationError`** **without** invoking the outbound HTTP transport for the denied vendor.

**Reference implementation:** `services/integration-ingress/src/integration_ingress/compliance_residency.py` (`is_residency_matrix_blocked`, `guard_osint_before_http`).

### 2.2.2 Policy-driven residency assertion

For permitted matrix states, the entity evaluates **tenant residency** against **vendor processing region** classifications. Upon violation, the system records **`record_residency_compliance_block`** metadata (including **outcome** classification such as **`compliance_block`**) and raises **`DataResidencyViolationError`** prior to transport.

**Reference implementation:** `services/integration-ingress/src/integration_ingress/compliance_residency.py` (`assert_vendor_residency_allowed` pathway within `guard_osint_before_http`).

### 2.2.3 Automated verification

Automated tests assert that **mock transports** configured to **fail if invoked** are **not** invoked when residency blocks apply, substantiating the **pre-socket** property.

**Reference tests:** `services/integration-ingress/tests/test_compliance_residency_osint.py`.

### 2.2.4 Shared library contract

The shared **`DataResidencyViolationError`** type documents the guarantee that the error is raised **before any outbound vendor HTTP** when tenant residency forbids the vendor processing region.

**Reference:** `services/core/src/tarka_core/data_residency.py`.

## 2.3 Evidence artifacts (non-exhaustive)

| Artifact | Description |
|----------|-------------|
| Compliance audit records | Records emitted via `record_residency_compliance_block` (fields: tenant, vendor, regions, outcome) |
| Application logs | Structured warnings with `audit_plane=compliance` |
| Policy configuration | Tenant residency configuration and matrix persistence (organization-defined) |
| Test execution records | CI output demonstrating transport non-invocation |

## 2.4 Complementary user entity controls (CUECs)

The service organization shall:

- Maintain **accurate** **tenant residency** attributes in authoritative **tenant configuration** stores.
- Review **matrix** blocks on a **periodic** basis and upon **contract** or **regulatory** change.

## 2.5 Cross-reference

Formal mapping to **TSC** and **PCI DSS** requirements appears in [Appendix A — Control mapping matrix](./Appendix-A-control-mapping-matrix.md).
