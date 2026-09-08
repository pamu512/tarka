# Production secrets rotation

Thin runbook. Rotate operator-supplied keys **without** a Vault / External Secrets Operator requirement. Kubernetes Secret + `global.appSecretsName` is enough. Vault/ESO remain optional.

Contract: [production-install-v1](../../contracts/production-install-v1.md). Helm presets: `prod-on-k8s`, `enterprise-desk-on-k8s`.

## What to rotate

| Secret key | Who consumes it | Overlap window |
|------------|-----------------|----------------|
| `API_KEYS` | Machines / evaluate (`X-API-Key`) | Comma-separated. Add the new key, roll callers, drop the old key. |
| `EVIDENCE_SIGNING_SECRET` | case-api HMAC (`CASE_API_PRODUCTION_MODE`) | Dual-read is **not** implemented. Rotate in a maintenance window; old evidence signatures will not verify. |
| `RULE_GOVERNANCE_SECRET` | Two-person live-rule | Same: one value. Coordinate the desk change with the Secret patch. |
| `OIDC_CLIENT_SECRET` | Desk humans (optional) | Rotate at the IdP, then patch the Secret. Empty issuer = unused. |
| `AGE_POSTGRES_PASSWORD` / `AGE_DATABASE_URL` | Hunt sidecar only | Change AGE auth and the URL together. Not core SoR. |
| Buyer `DATABASE_URL` / `REDIS_URL` | External stores | Rotate in the buyer store, then re-run `generate_cloud_values.py` (or patch the values file). |

Do not put replacement values in Helm values, git, or compose production examples.

## Kubernetes Secret (no Vault)

```bash
# Create once (example keys only — generate your own).
kubectl create secret generic tarka-app-secrets \
  --from-literal=API_KEYS="$(openssl rand -hex 32)" \
  --from-literal=EVIDENCE_SIGNING_SECRET="$(openssl rand -hex 32)" \
  --from-literal=RULE_GOVERNANCE_SECRET="$(openssl rand -hex 32)"
# enterprise-desk also needs AGE_POSTGRES_PASSWORD + AGE_DATABASE_URL
# (Hunt sidecar; not core SoR). Add them when that preset is on.

# Helm already points at it:
#   --set global.appSecretsName=tarka-app-secrets
```

Patch + restart (API keys with overlap):

```bash
# 1. Read current keys, append the new one (operator-local; do not echo into tickets).
kubectl get secret tarka-app-secrets -o jsonpath='{.data.API_KEYS}' | base64 -d
# 2. Patch both keys into the Secret (old,new). GNU or BSD base64:
b64=$(printf '%s' 'old-key,new-key' | base64 | tr -d '\n')
kubectl patch secret tarka-app-secrets --type merge -p "{\"data\":{\"API_KEYS\":\"${b64}\"}}"
# 3. Secret env is fixed at pod start. Roll every Deployment that mounts
#    global.appSecretsName. helm upgrade --install tarka names core-api
#    tarka-tarka-core-api (not app=tarka-core-api).
kubectl rollout restart deploy/tarka-tarka-core-api
# 4. Point callers at new-key, then patch Secret to new-key only and roll again.
```

Signing / governance secrets: skip the overlap step. Patch the single value, then roll.

## Fail closed

Empty `API_KEYS` + empty `OIDC_ISSUER` + `allowInsecureNoAuth=false` is **503**, not open evaluate. A botched rotation that leaves `API_KEYS` empty will refuse traffic. That is intended.

`TARKA_DEPLOYMENT_PROFILE=production` also refuses `ALLOW_INSECURE_NO_AUTH=true`.

## Optional tooling

AWS Secrets Manager, GCP Secret Manager, Vault, or External Secrets can populate the same Kubernetes Secret. None of them are required to claim a production-shaped install. G4 wires first-class OIDC; this runbook does not.
