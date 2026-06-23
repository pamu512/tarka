# Staging preset promotion playbook

Promote cloud Helm presets from CI-generated artifacts to the staging overlay without manual YAML editing.

## Prerequisites

- `python3`, repo checkout on `master`
- Staging cluster credentials (kubectl context `staging`)
- Secrets in cluster: `tarka-app-secrets` with `API_KEYS`, `DATABASE_URL` overrides as needed

## Steps

1. **Generate and validate locally**

   ```bash
   chmod +x infra/scripts/deploy/promote_preset.sh
   IMAGE_REGISTRY=your.registry/tarka ./infra/scripts/deploy/promote_preset.sh core-on-aws
   ```

2. **Review diff**

   ```bash
   git diff infra/deploy/hosted/k8s/overlays/staging/
   git diff infra/deploy/generated/
   ```

3. **CI gate** — merge only when `cloud-preset-smoke` job is green on the PR.

4. **Apply to staging**

   ```bash
   helm upgrade --install tarka-staging infra/deploy/helm/fraud-stack \
     -f infra/deploy/hosted/k8s/overlays/staging/core-on-aws.values.yaml \
     -n tarka-staging --create-namespace
   ```

5. **Smoke**

   - `kubectl get pods -n tarka-staging`
   - `curl -sf http://<ingress>/health` on graphql-gateway / core-api
   - Run `infra/scripts/ci/cloud_preset_smoke.py` if regenerating values

## Presets

| Preset | Use case |
|--------|----------|
| `core-on-aws` | AWS managed DB/Redis |
| `core-on-gcp` | GCP managed services |
| `investigation-on-aws` | Core + investigation-agent |
| `full-on-k8s` | In-cluster data plane |

## Rollback

Keep previous values file in git tag; `helm rollback tarka-staging <revision>`.

## Related

- [deployment-presets.md](./deployment-presets.md)
- [runbook-pack-index.md](../operations/runbook-pack-index.md)
