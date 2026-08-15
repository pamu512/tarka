# SRE runbook — Linux Compose profiles

**Audience:** on-call / platform SRE.  
**Default production shape:** one Linux VM (or a small VM pair), Docker Compose v2.  
**Not required:** Apple Silicon, JanusGraph, or Ollama.

Day-1 is **desk**. Graph, async ingest, and local Shadow are add-on profiles. Do not colocate JanusGraph and Ollama on the evaluate host.

Related: [ports](../guides/service-ports.md) · [SLOs](../guides/service-slos-v1.md) · [SLO burn](./slo-burn-response.md) · [common failures](./runbook-common-failures.md) · [on-call](./oncall-playbook.md) · [15-minute first decision](../guides/oss-15-minute-first-decision.md)

---

## What pages vs what degrades

| Symptom | Severity | Action |
|---------|----------|--------|
| `core-api` `/decisions/v1/health` or `/decisions/v1/ready` down | **Page** | Evaluate is the allow/deny path. See [common failures](./runbook-common-failures.md). |
| Postgres or Redis down | **Page** | Desk cannot persist audit / velocities. |
| Graph / Janus / Gremlin down | Degrade | Evaluate should fail-open with `graph:unavailable` when circuits are on. Do not block payments to save the graph. |
| Data-plane / NATS down | Degrade (sync desk still up) | Async `/v1/events` stalls. Sync `POST /v1/ingest` / evaluate still work if core-api is up. |
| Shadow / LLM down | Degrade | Forensics only. AI never owns allow/deny. Self-hosted Ollama/vLLM **or** Claude / Gemini / Qwen via `SHADOW_LLM_BACKEND`. |
| Fingerprint / Incognia upstream 5xx | Degrade | Partner fusion fail-closed for that vendor; rules must still evaluate without vendor tags. |

---

## Profiles (planning floors)

RAM is **host free memory** for that compose set, not a measured SLO. SSD. x86_64 or aarch64 Linux. Docker Compose v2. Python ≥ 3.11 on the operator laptop only if you run smoke scripts on the host.

| Profile | Compose | Services (typical) | Linux RAM floor | When to turn on |
|---------|---------|--------------------|-----------------|-----------------|
| **Desk** | `docker-compose.lite.yml` + `docker-compose.fraud-desk.yml` | postgres, redis, nats, core-api, signal-api, integration-ingress, frontend | **~8 GB** | Default. Decision + cases. No graph, no Ollama. |
| **+ ingest** | lite + `docker-compose.demo-vertical.yml` `--profile ingest` (or data-plane on main compose `streaming`) | data-plane `:8007`, NATS JetStream | **+2–4 GB** | Async `POST /v1/events`. Set `ORCHESTRATOR_URL` only if orchestrator is on the same network. |
| **+ graph** | lite `--profile graph` | janusgraph (Gremlin `:8182`), graph-service `:8001` | **+8 GB** | Topology / multi-account edges. Optional. Not on the evaluate host if you can split VMs. |
| **+ Shadow** | `docker-compose.v2-ingest.yml` (orchestrator + shadow_agent) | shadow_agent + LLM | **+8 GB** only if the model is **on this host** (Ollama/vLLM 7B-class). API backends (Claude / Gemini / Qwen) add ~256 MB. | Forensics. Advise only. Set `SHADOW_LLM_BACKEND`. |
| **Full triad on one box** | desk + graph + large local LLM | all of the above | **~24 GB+** | Lab / demo. Not the production default. |

Disk: **≥ 20 GB** free for desk images; **≥ 40 GB** if you also store 30B-class weights.

---

## Bring-up (desk)

From repo root:

```bash
cp infra/deploy/env/community.env.example infra/deploy/.env
# Production: set API_KEYS. Do not set ALLOW_INSECURE_NO_AUTH=true.

docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  --env-file infra/deploy/.env \
  up -d --build
```

Wait until healthy, then:

```bash
curl -sf http://127.0.0.1:8000/decisions/v1/health >/dev/null && echo core-api_ok
curl -sf http://127.0.0.1:8000/decisions/v1/ready >/dev/null && echo core-api_ready
```

First decision (needs `ALLOW_INSECURE_NO_AUTH=true` only on a throwaway box):

```bash
python3 scripts/oss/first_decision_smoke.py
```

UI: `http://127.0.0.1:3000` (desk-strict: no auto mocks).

### Add graph (optional)

```bash
docker compose -f infra/deploy/docker-compose.lite.yml --profile graph up -d --build
curl -sf http://127.0.0.1:8001/v1/health >/dev/null && echo graph_ok
```

Point `GRAPH_SERVICE_URL=http://graph-service:8001` on core-api if you want evaluate to read graph signals.

### Add async ingest (optional)

Data-plane health: `http://127.0.0.1:8007/v1/health`. Consumer durable is `decision-worker`. Do not also run a second evaluate consumer on the same stream.

---

## Partner fusion (Fingerprint / Incognia)

Tarka does not replace those vendors. If the tenant already has them:

```bash
export TARKA_VENDOR_FINGERPRINT_API_KEY=...
export TARKA_VENDOR_INCOGNIA_CLIENT_ID=...
export TARKA_VENDOR_INCOGNIA_CLIENT_SECRET=...
```

Evaluate metadata: `fingerprint_request_id`, `incognia_account_id`. Proof: `python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture` (no keys). Live mode needs real request/account ids.

**Radar (radar.com)** is not a Tarka vendor plugin. Keep trip/geofence decisions in Radar. Catalog `stripe_radar` is a different product.

---

## Split hosts (recommended once desk is live)

| VM | Runs | Why |
|----|------|-----|
| **evaluate** | postgres, redis, nats, core-api, signal-api, frontend | Hot path. Page this box. |
| **graph** (optional) | Janus/Gremlin + graph-service | Isolate Gremlin heap from evaluate p95. |
| **forensics** (optional) | shadow_agent + Ollama | Isolate model weights. Outage ≠ deny. |

Do not put Janus + Ollama + evaluate on one VM and call it production.

---

## Health and ports (desk)

| Check | URL |
|-------|-----|
| Decision health | `GET http://<host>:8000/decisions/v1/health` |
| Decision ready | `GET http://<host>:8000/decisions/v1/ready` |
| Signal API | `GET http://<host>:8004/v1/health` (if exposed) |
| Frontend | `GET http://<host>:3000/` |
| Graph (profile on) | `GET http://<host>:8001/v1/health` |
| Data-plane (profile on) | `GET http://<host>:8007/v1/health` |

Full port map: [service-ports.md](../guides/service-ports.md).

---

## Shadow LLM (`SHADOW_LLM_BACKEND`)

Default **ollama** (self-hosted). Same env on `shadow_agent`. Details: `services/shadow_agent/README.md`.

| Backend | Env |
|---------|-----|
| Self-hosted Ollama | `SHADOW_LLM_BACKEND=ollama` `OLLAMA_HOST=http://ollama:11434` |
| Self-hosted vLLM / any OpenAI-compat | `SHADOW_LLM_BACKEND=self-hosted` `SHADOW_LLM_BASE_URL=http://vllm:8000/v1` |
| Claude | `SHADOW_LLM_BACKEND=claude` `ANTHROPIC_API_KEY=…` |
| Gemini | `SHADOW_LLM_BACKEND=gemini` `GEMINI_API_KEY=…` |
| Qwen (DashScope) | `SHADOW_LLM_BACKEND=qwen` `DASHSCOPE_API_KEY=…` |

`SHADOW_LLM_MODEL` overrides the preset model. Timeout → inconclusive Shadow decision, not allow/deny.

---

## After an incident

1. [SLO burn](./slo-burn-response.md) if Prometheus fired.  
2. [Fallback / emergency](../guides/fallback-emergency-runbook.md) for tenant kill switches and circuits.  
3. [Degraded operations](../guides/degraded-operations.md) if investigation/Shadow is the only broken piece.

Publish any latency number with: Linux SKU or instance type, compose files + profiles, commit SHA, warm-up count. Do not cite the old laptop triad as an SLO.
