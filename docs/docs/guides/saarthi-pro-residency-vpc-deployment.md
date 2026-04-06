# Saarthi Pro — residency, VPC, and data-boundary deployment

> **Internal solutions architecture.** Aligns with BYOK and procurement questions. Technical controls = network + env + Customer’s LLM contract.

## Data flows (summary)

1. **Analyst → agent:** prompts, optional files, headers (identity).
2. **Agent → Customer APIs:** case, graph, decision calls (Customer SoR).
3. **Agent → LLM:** completions when BYOK or bundled inference keys are set; payloads include tool results and truncated context.

**Residency** is determined by: (a) where the **agent** runs, (b) where **Customer APIs** run, (c) where the **LLM** endpoint resolves (Customer’s Azure region, etc.).

## VPC / private deployment patterns

| Pattern | Description |
|---------|-------------|
| **Customer VPC** | Agent containers in Customer AWS/GCP/Azure; egress allowlist to Customer case APIs + LLM endpoint only. |
| **Vendor-managed VPC** | Dedicated VPC with Customer peering or PrivateLink to Customer APIs; no internet egress except allowlisted LLM. |
| **Split** | Agent in Customer VPC; LLM via Customer’s private endpoint (e.g. Azure OpenAI VNet integration). |

## Checklist

- [ ] Document all **egress URLs** (case, graph, decision, LLM, optional telemetry).
- [ ] No agent-initiated egress to public internet except allowlisted.
- [ ] Secrets in KMS / secret manager; not in Compose files in prod.
- [ ] Logs: redact or avoid full PII in access logs; correlate `turn_id` for support.
- [ ] `GET /v1/governance` and `AI_GOVERNANCE_PROFILE` set per [AI governance regional builds](ai-governance-regional-builds.md) if jurisdiction-specific copy required.

## LLM subprocessor minimization

- **Pure BYOK:** Customer DPA with model vendor; Vendor’s DPA covers agent runtime only.
- **Bundled inference:** Vendor’s subprocessor list must name model provider and region.

## Related

- [SSO / SCIM guide](saarthi-pro-sso-scim-integration-guide.md)
- [DPA template](saarthi-pro-dpa-subprocessor-template.md)
- [Production hardening overlay](../../../deploy/docker-compose.production-hardening.yml) (reference path from repo root)
