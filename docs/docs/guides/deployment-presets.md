# Cloud presets and generated values

This guide provides low-touch deployment presets for AWS and GCP and a generator script that writes ready-to-review Helm values files.

---

## Supported presets

| Preset | Purpose | Clouds |
|---|---|---|
| `core-on-aws` | Decisioning-focused baseline with managed data services | AWS |
| `investigation-on-aws` | Analyst workflows and collaboration baseline | AWS |
| `core-on-gcp` | Decisioning baseline on GKE + Cloud SQL + Memorystore | GCP |
| `full-on-k8s` | Full platform baseline for Kubernetes-first environments | Any |

Preset files live in `deploy/helm/fraud-stack/presets/`.

---

## Generate values from preset

From repository root:

```bash
python3 scripts/deploy/generate_cloud_values.py \
  --preset core-on-aws \
  --namespace fraud \
  --image-registry 123456789012.dkr.ecr.us-east-1.amazonaws.com/tarka \
  --db-url postgresql+asyncpg://fraud:***@db.internal:5432/fraud \
  --redis-url redis://cache.internal:6379/0 \
  --output deploy/generated/core-on-aws.values.yaml
```

For GCP:

```bash
python3 scripts/deploy/generate_cloud_values.py \
  --preset core-on-gcp \
  --namespace fraud \
  --image-registry us-central1-docker.pkg.dev/my-project/tarka \
  --db-url postgresql+asyncpg://fraud:***@10.20.0.3:5432/fraud \
  --redis-url redis://10.30.0.4:6379/0 \
  --output deploy/generated/core-on-gcp.values.yaml
```

---

## Deploy with generated values

```bash
helm upgrade --install tarka deploy/helm/fraud-stack \
  --namespace fraud \
  --create-namespace \
  --values deploy/generated/core-on-aws.values.yaml
```

---

## Operator notes

- Generated files are templates for review; treat them as environment configuration artifacts.
- Keep runtime credentials in secret managers and/or Kubernetes Secrets, not inline strings.
- Start with `core` presets and layer additional modules after smoke checks pass.
