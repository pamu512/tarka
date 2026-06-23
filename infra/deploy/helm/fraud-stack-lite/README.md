# fraud-stack-lite

Minimal Helm chart for Tarka Lite deployments:
- `core-fraud-api`
- `data-platform`
- `investigation-agent`

Use:

```bash
helm lint infra/deploy/helm/fraud-stack-lite
helm template tarka-lite infra/deploy/helm/fraud-stack-lite
```

