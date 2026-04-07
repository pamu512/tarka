# Deploying Tarka on Microsoft Azure

This guide maps the **reference** deployment artifacts in this repo ([Docker Compose](../../../deploy/docker-compose.yml), [Helm chart](../../../deploy/helm/fraud-stack/)) to a typical **Microsoft Azure** production layout. It is **not** a turnkey Bicep/ARM template; it describes what to provision, how components align, and where secrets and URLs belong.

**See also:** [Deployment Guide](./deployment.md) (Compose profiles, Helm install, env reference), [Service ports](./service-ports.md), [Enterprise readiness](./enterprise-readiness.md).

---

## Recommended shape

| Concern | Azure service (typical) | Notes |
|--------|-------------------------|--------|
| **Kubernetes** | **Azure Kubernetes Service (AKS)** | Use **availability zones** for the node pool; enable cluster autoscaler if traffic is variable. |
| **Ingress / TLS** | **Application Gateway** + [Application Gateway Ingress Controller (AGIC)](https://azure.github.io/application-gateway-kubernetes-ingress/) or **NGINX Ingress** + **cert-manager** | Terminate TLS at the gateway or ingress; use **Key Vault**-backed certificates where policy requires it. |
| **Container images** | **Azure Container Registry (ACR)** | Build from repo root with `services/*/Dockerfile`; use **geo-replication** if you operate multiple regions. |
| **Relational DB** | **Azure Database for PostgreSQL – Flexible Server** | Host one or two **databases** on the same server (e.g. `fraud`, `fraud_cases`) for Decision API and Case API, or separate servers for stronger isolation. |
| **Cache** | **Azure Cache for Redis** | Enable TLS and access keys / Entra ID auth per your standard. |
| **Graph** | **Neo4j Aura**, Neo4j on AKS, or **JanusGraph** on VMs/AKS | Match HA and backup requirements to your graph backend. |
| **Streaming (optional)** | **NATS** in-cluster (Helm chart) or dedicated nodes | Event-ingest pipeline; size persistence for JetStream retention. |
| **Analytics (optional)** | **ClickHouse** on AKS or managed analytics store | Reference chart runs ClickHouse in-cluster. |
| **Secrets** | **Azure Key Vault** | Store `OPENAI_API_KEY`, `API_KEYS`, DB passwords, Redis keys, signing secrets. |
| **Pod identity** | **Workload Identity** (federated credentials) | Prefer over long-lived kube secrets mounted from static files. |

---

## Helm chart and managed data stores

The bundled Helm chart (`deploy/helm/fraud-stack`) defaults to **in-cluster** PostgreSQL and Redis (`templates/decision-api.yaml` wires `DATABASE_URL` / `REDIS_URL` to those Services).

For **Flexible Server** and **Azure Cache for Redis**, production deployments typically:

1. Set `postgres.enabled: false` and `redis.enabled: false` in `values.yaml` **after** you introduce a **patch, Kustomize overlay, or wrapper chart** that injects `DATABASE_URL`, `REDIS_URL`, and related env vars from **Kubernetes Secrets** populated by **Key Vault** (e.g. [Secrets Store CSI driver](https://azure.github.io/secrets-store-csi-driver-provider-azure/)), **or**
2. Use a GitOps pipeline that renders manifests with the correct async URLs (`postgresql+asyncpg://…` for the Python services).

Plan this customization before relying on managed databases with the stock templates.

---

## Image build and ACR

From the **repository root**:

```bash
az acr login --name <registryName>

# Example: decision-api
docker build -f services/decision-api/Dockerfile -t <registryName>.azurecr.io/tarka/decision-api:<tag> .
docker push <registryName>.azurecr.io/tarka/decision-api:<tag>
```

Configure AKS to pull from ACR ([AcrPull role](https://learn.microsoft.com/azure/container-registry/container-registry-auth-aks) or OIDC workload identity). Align Helm `image` / `tag` (and optional `global.imageRegistry`) with your ACR host.

---

## Networking

- Deploy AKS into a **virtual network** with separate subnets for nodes and **Application Gateway** (if used).
- Use **private endpoints** for PostgreSQL Flexible Server and Key Vault where required by policy.
- **Network Security Groups:** restrict Postgres (5432) and Redis (6380/6379) to cluster/VNet sources only.

---

## Observability

- **Azure Monitor** for containers (metrics/logs) integrates with AKS; or deploy **Prometheus/Grafana** similarly to [deploy/observability](../../../deploy/observability/README.md).
- Use **`/v1/health`** for Kubernetes **liveness** and **readiness** probes on each service.

---

## Investigation agent / LLM egress

Outbound calls from `investigation-agent` to `OPENAI_BASE_URL` require **controlled egress** (firewall, proxy, or private endpoints) if your policy restricts public internet. For EU/UK deployments, consider regional governance overlays: [AI governance regional builds](./ai-governance-regional-builds.md) and [LLM data flow](./investigation-agent-llm-data-flow.md).

---

## Checklist (Azure)

- [ ] AKS with zone-redundant node pools (if SLA requires)  
- [ ] PostgreSQL Flexible Server + backup retention + high availability tier if needed  
- [ ] Azure Cache for Redis (TLS, key rotation)  
- [ ] ACR with private endpoint or trusted services access  
- [ ] Key Vault + workload identity / CSI for runtime secrets  
- [ ] Ingress + TLS + (optional) WAF / Front Door for public entry  
- [ ] Helm overlay for **managed** DB/Redis URLs when not using in-cluster data stores  
- [ ] `API_KEYS`, `CORS_ORIGINS`, rate limits per [Deployment Guide](./deployment.md#security-hardening-checklist)  

---

## Further reading

- [AKS baseline architecture](https://learn.microsoft.com/azure/architecture/reference-architectures/containers/aks-baseline)  
- [Azure Well-Architected Framework — Security](https://learn.microsoft.com/azure/well-architected/security/)  
