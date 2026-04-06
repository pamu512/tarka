# Saarthi Pro — SSO (SAML/OIDC) & SCIM integration guide

> **Internal architecture guide.** The investigation agent today is typically fronted by **API keys** or a **gateway**. Enterprise IdP integration is implemented **outside** the agent core unless/until native OIDC is productized.

## Recommended pattern: gateway in front of the agent

```text
[Browser / client] → [Enterprise IdP SAML/OIDC] → [API gateway / BFF]
       → [Investigation agent] → [Case / Graph / Decision APIs]
```

**Responsibilities**

| Layer | Authentication | Authorization |
|-------|----------------|-----------------|
| **IdP** | User login (SAML/OIDC) | Groups / roles claims |
| **Gateway** | Validates JWT or session; may mint **service** API key to agent | Maps IdP groups → `x-analyst-id` / tenant headers; enforces route RBAC |
| **Agent** | `API_KEYS` or forwarded trust headers (deployment-specific) | `ALLOWED_ANALYSTS`, tool policies, maker–checker |

## OIDC (preferred for new deployments)

1. Register confidential client in IdP (Auth0, Okta, Azure AD, Keycloak).
2. Gateway performs OIDC code flow for interactive users; for **server-to-server** chat from a backend, use **client credentials** or **token exchange** to a gateway-issued token.
3. Gateway injects stable **`analyst_id`** (subject or mapped claim) on requests to `POST /v1/chat` / stream.
4. Set **`COPILOT_REQUIRE_INVESTIGATION_API_KEY=true`** on the agent; gateway holds the key or mTLS secret.

## SAML

Use a gateway that terminates SAML (e.g. oauth2-proxy with SAML provider, Kong, NGINX Plus, cloud load balancer). Same downstream pattern: gateway → agent with API key + analyst identity headers.

## SCIM

SCIM provisions **users and groups** in the **customer’s directory** and optionally in the **gateway’s** user store. The investigation agent does **not** require SCIM natively.

- **Provision** analysts in IdP → gateway reads group membership on each request.
- **Deprovision:** remove from IdP group; gateway denies next request.

Document **which system is SoR for analyst identity** in the security appendix.

## Hardening checklist

- [ ] No IdP secrets in agent env; only gateway ↔ agent trust.
- [ ] TLS end-to-end; optional mTLS gateway → agent in VPC.
- [ ] Audit logs: gateway request id + analyst id correlated with agent `turn_id` / structured logs.
- [ ] Rate limits at gateway for `/v1/chat` and `/v1/chat/stream`.

## Related

- [Residency & VPC deployment](saarthi-pro-residency-vpc-deployment.md)
- [Managed operations runbook](saarthi-pro-managed-operations-runbook.md)
