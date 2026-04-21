# Deploying Tarka on AWS

This guide maps the **reference** deployment artifacts in this repo ([Docker Compose](../../../deploy/docker-compose.yml), [Helm chart](../../../deploy/helm/fraud-stack/)) to a typical **Amazon Web Services** production layout. It is **not** a one-click Terraform module; it describes what to provision, how services fit together, and where to inject secrets and URLs.

**See also:** [Deployment Guide](./deployment.md) (Compose profiles, Helm install, env reference), [Service ports](./service-ports.md), [Cloud presets and generated values](./deployment-presets.md), [Enterprise readiness](./enterprise-readiness.md).

---

## Recommended shape

| Concern | AWS service (typical) | Notes |
|--------|------------------------|--------|
| **Kubernetes** | **Amazon EKS** | Run application workloads; use at least two nodes across AZs for HA. |
| **Ingress / TLS** | **Application Load Balancer** via [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/) | Terminate TLS at the ALB; use ACM certificates. |
| **Container images** | **Amazon ECR** | Build images from `services/*/Dockerfile` (repo root context); push tags per service. |
| **Relational DB** | **Amazon RDS for PostgreSQL** | Decision API and Case API can share a cluster with **two databases** (e.g. `fraud` and `fraud_cases`) or separate instances—match your isolation policy. |
| **Cache** | **ElastiCache for Redis** | Single primary + replica for HA; use TLS and auth token in production. |
| **Graph** | **Neo4j Aura**, self-managed Neo4j on EKS, or **JanusGraph** on EC2/EKS | Community Neo4j is single-node; plan backups and upgrades. |
| **Streaming (optional)** | **NATS** in-cluster (chart includes `nats`) or self-managed on EC2 | Event-ingest path; size JetStream storage for retention. |
| **Analytics (optional)** | **ClickHouse** on EKS or **Altinity.Cloud** / Bring-your-own | Chart includes in-cluster ClickHouse for reference. |
| **Secrets** | **AWS Secrets Manager** or **SSM Parameter Store** | `OPENAI_API_KEY`, `API_KEYS`, `ATTESTATION_HMAC_SECRET`, DB passwords, Redis AUTH. |
| **Pod identity** | **IAM Roles for Service Accounts (IRSA)** | Let workloads read specific secrets or reach KMS without long-lived keys on disk. |

---

## Helm chart and managed data stores

The bundled Helm chart (`deploy/helm/fraud-stack`) wires `DATABASE_URL` and `REDIS_URL` to **in-cluster** Postgres and Redis by default (see `templates/decision-api.yaml` and similar).

For **RDS** and **ElastiCache**, production teams usually:

1. **Disable** chart-managed Postgres/Redis in `values.yaml` (`postgres.enabled: false`, `redis.enabled: false`) once you have a patch or overlay that sets env vars from **Kubernetes Secrets** (synced from Secrets Manager via [External Secrets Operator](https://external-secrets.io/) or mounted by your CD pipeline), **or**
2. Maintain a **thin wrapper chart** or **Kustomize** layer that replaces `DATABASE_URL` / `REDIS_URL` / `NEO4J_URI` with references to your managed endpoints.

Until those URLs are configurable purely from `values.yaml`, treat the chart as a **starting point** for EKS and plan a small customization layer for managed backing services.

---

## Image build and ECR

From the **repository root** (Docker build context is `.`):

```bash
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com

# Example: decision-api
docker build -f services/decision-api/Dockerfile -t <account>.dkr.ecr.<region>.amazonaws.com/tarka/decision-api:<tag> .
docker push <account>.dkr.ecr.<region>.amazonaws.com/tarka/decision-api:<tag>
```

Repeat for each enabled service (`graph-service`, `case-api`, `investigation-agent`, etc.). Point Helm `global.imageRegistry` / per-service `image` and `tag` at your ECR paths.

### Guided preset bootstrap

Use the preset generator for a quick starting values file:

```bash
python3 scripts/deploy/generate_cloud_values.py \
  --preset core-on-aws \
  --image-registry <account>.dkr.ecr.<region>.amazonaws.com/tarka \
  --db-url postgresql+asyncpg://fraud:***@<rds-host>:5432/fraud \
  --redis-url redis://<elasticache-host>:6379/0 \
  --output deploy/generated/core-on-aws.values.yaml
```

---

## Networking

- Place EKS worker nodes in **private subnets**; use a public ALB only for ingress to the UI / gateway / public APIs.
- **Security groups:** allow app subnets → RDS/ElastiCache only on required ports (5432, 6379); no database ports on `0.0.0.0/0`.
- **VPC endpoints** (optional): ECR, S3, Secrets Manager—reduce NAT dependency and tighten egress.

---

## Observability

- **Amazon CloudWatch** for logs (DaemonSet / Fluent Bit) and metrics; or keep the optional [Prometheus + Grafana compose add-on](../../../deploy/observability/README.md) pattern and run the same stack on EKS via Prometheus Operator.
- All Tarka HTTP services expose **`/v1/health`**; use those for **liveness/readiness** probes.

---

## Investigation agent / LLM egress

If you use `investigation-agent` with a **public** LLM API, egress goes to the internet (or through a **NAT Gateway** / **egress firewall**). For stricter data residency, run inference in **VPC-only** endpoints or self-hosted models and set `OPENAI_BASE_URL` accordingly. See [Investigation Copilot — LLM data flow](./investigation-agent-llm-data-flow.md).

---

## Checklist (AWS)

- [ ] EKS cluster + IRSA for least-privilege AWS API access  
- [ ] RDS PostgreSQL (Multi-AZ if required) + automated backups  
- [ ] ElastiCache Redis with AUTH and in-transit encryption  
- [ ] ECR repos + image signing / immutable tags (policy)  
- [ ] ALB + ACM TLS + WAF (optional) in front of public routes  
- [ ] Secrets Manager / SSM for credentials; no secrets in Git  
- [ ] Patch or overlay Helm env for **managed** `DATABASE_URL` / `REDIS_URL` when not using in-cluster DBs  
- [ ] `API_KEYS` and `CORS_ORIGINS` set per [Deployment Guide](./deployment.md#security-hardening-checklist)  

---

## Further reading

- [AWS Well-Architected — Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html)  
- [EKS Best Practices Guide](https://aws.github.io/aws-eks-best-practices/)
