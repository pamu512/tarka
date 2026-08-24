# SRE runbook — Linux Compose profiles

**Audience:** on-call / platform SRE.  
**Default production shape:** one Linux VM (or a small VM pair), Docker Compose v2.  
**Not required:** Apple Silicon, JanusGraph, or Ollama.

Day-1 is **evaluate-only** (Rust packs + `core-api` + thin desk). Graph, signals, investigation, async ingest, and local Shadow are add-on overlays. Empty plane URL = plane off. Do not colocate JanusGraph and Ollama on the evaluate host.

Architecture pointer (do not treat that file as the Day-1 process list): repo-root [`ARCHITECTURE.md`](../../../ARCHITECTURE.md).

Related: [ports](../guides/service-ports.md) · [SLOs](../guides/service-slos-v1.md) · [SLO burn](./slo-burn-response.md) · [common failures](./runbook-common-failures.md) · [on-call](./oncall-playbook.md) · [15-minute first decision](../guides/oss-15-minute-first-decision.md)

---

## What pages vs what degrades

| Symptom | Severity | Action |
|---------|----------|--------|
| `core-api` `/decisions/v1/health` or `/decisions/v1/ready` down | **Page** | Evaluate is the allow/deny path. See [common failures](./runbook-common-failures.md). |
| Postgres or Redis down | **Page** | Desk cannot persist audit / velocities. |
| Graph / Janus / Gremlin down | Degrade | Evaluate fail-opens with `graph:unavailable` when `GRAPH_SERVICE_URL` is set. Empty URL tags `graph:unconfigured` (no 2.5s timeout). Do not block payments to save the graph. |
| Data-plane / NATS / orchestrator / outbox down | Degrade (sync desk still up) | Async `/v1/events` stalls or side-effects NAK. Sync evaluate still works if core-api is up. |
| Shadow / LLM down | Degrade | Forensics only. AI never owns allow/deny. Self-hosted Ollama/vLLM **or** Claude / Gemini / Qwen via `SHADOW_LLM_BACKEND`. |
| Fingerprint / Incognia upstream 5xx | Degrade | Partner fusion fail-closed for that vendor; rules must still evaluate without vendor tags. |

---

## Profiles (planning floors)

RAM is **host free memory** for that compose set, not a measured SLO. SSD. x86_64 or aarch64 Linux. Docker Compose v2. Python ≥ 3.11 on the operator laptop only if you run smoke scripts on the host.

| Profile | Compose | Services (typical) | Linux RAM floor | When to turn on |
|---------|---------|--------------------|-----------------|-----------------|
| **Evaluate-only / thin desk** | `docker-compose.lite.yml` (optional `docker-compose.fraud-desk.yml`) | postgres, redis, core-api, frontend | **~3 GB** | **Day-1 default.** Rust evaluate + packs. Lean `/decisions` + `/rules` (+ residual `/cases`). No nats, no signal-api, no investigation-agent, no ingress. |
| **+ investigation** | lite + `docker-compose.investigation.yml` | investigation-agent `:8006` | **+1–2 GB** | Advise / copilot. Sets desk `VITE_INVESTIGATION_AGENT_URL`. Empty URL hides Advise chrome. |
| **+ signals** | lite + `docker-compose.signals.yml` | nats, signal-api `:8004`, integration-ingress `:8003` | **+2–3 GB** | Features / ML / calibration + ingress. Sets `FEATURE_SERVICE_URL` / `ML_SCORING_URL` and desk `VITE_SIGNAL_API_URL`. |
| **Full desk** | `docker-compose.full-desk.yml` (lite + fraud-desk + signals + investigation) | evaluate-only plus nats, signal-api, ingress, investigation-agent | **~8 GB** | Former "Desk" shape. Analyst tools. Still no graph, no Ollama. |
| **+ ingest** | lite `--profile ingest` (optional `docker-compose.demo-vertical.yml`) | data-plane `:8007`, orchestrator `:8790`, outbox-processor, NATS JetStream | **+3–5 GB** | Async `POST /v1/events`. Same `ALLOW_INSECURE_NO_AUTH` / `API_KEYS` as core-api (consumer uses `UPSTREAM_API_KEY` or first `API_KEYS`). Durable is `decision-worker`. nginx `/api/orchestrator` and `/api/v1/demo` 503 without this profile. |
| **+ OPA** | full compose `--profile opa` | `openpolicyagent/opa` `:8181` | **+256 MB** | Set `OPA_URL=http://opa:8181` on core-api. Empty URL skips the hop (no 2s timeout). Not part of `--profile full`. |
| **+ graph** | lite `--profile graph` + `docker-compose.graph-wire.yml` | janusgraph/janusgraph:1.0.0 (BerkeleyJE volume, Gremlin `:8182`), graph-service `:8001` | **+8 GB** | Topology / multi-account edges. Overlay sets `GRAPH_SERVICE_URL` / desk `VITE_GRAPH_SERVICE_URL`. Empty URL hides Graph nav (honest "plane off", not a 503 tab). |
| **+ Shadow** | `docker-compose.v2-ingest.yml` (orchestrator + shadow_agent) | shadow_agent + LLM | **+8 GB** only if the model is **on this host** (Ollama/vLLM 7B-class). API backends (Claude / Gemini / Qwen) add ~256 MB. | Forensics. Advise only. Set `SHADOW_LLM_BACKEND`. |
| **Full triad on one box** | full desk + graph + large local LLM | all of the above | **~24 GB+** | Lab / demo. Not the production default. |

Helm chart `values.yaml` defaults match evaluate-only (`investigationAgent` / `signalApi` / `integrationIngress`: false). Sketch: `infra/deploy/helm/fraud-stack/presets/evaluate-only.yaml`. `prod-on-k8s` is a separate HA overlay — do not treat it as this Day-1 shape.

Disk: **≥ 12 GB** free for evaluate-only images; **≥ 20 GB** for full desk; **≥ 40 GB** if you also store 30B-class weights.

---

## Bring-up (evaluate-only / thin desk)

From repo root:

```bash
cp infra/deploy/env/community.env.example infra/deploy/.env
# Production: set API_KEYS. Do not set ALLOW_INSECURE_NO_AUTH=true.

# Evaluate-only (no agent / signal-api / ingress):
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  --env-file infra/deploy/.env \
  up -d --build

# Thin desk UI (lean nav + desk-strict) on the same process list:
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  --env-file infra/deploy/.env \
  up -d --build
```

### Add investigation (optional)

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.investigation.yml \
  up -d --build
curl -sf http://127.0.0.1:8006/v1/ready >/dev/null && echo investigation_ok
```

### Add signals (optional)

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.signals.yml \
  up -d --build
curl -sf http://127.0.0.1:8004/v1/health >/dev/null && echo signal_ok
```

### Full desk (former ~8 GB "Desk")

```bash
docker compose -f infra/deploy/docker-compose.full-desk.yml up -d --build
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
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.graph-wire.yml \
  --profile graph up -d --build
curl -sf http://127.0.0.1:8001/v1/health >/dev/null && echo graph_ok
```

`graph-wire.yml` sets `GRAPH_SERVICE_URL=http://graph-service:8001` on core-api. Without it, evaluate tags `graph:unconfigured` and skips the hop.

Ingest + graph (outbox writes Gremlin). `graph-wire.yml` sets `GREMLIN_REMOTE_URL` on orchestrator/outbox. Do not set that URL when `--profile graph` is off (NullGraphClient).

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.graph-wire.yml \
  --profile graph --profile ingest up -d --build
```

Full compose with graph writes: also merge `docker-compose.graph-env.yml` (same Gremlin env; janusgraph is in `--profile full` / `--profile graph`).

### Add async ingest (optional)

```bash
docker compose -f infra/deploy/docker-compose.lite.yml --profile ingest up -d --build
curl -sf http://127.0.0.1:8007/v1/health >/dev/null && echo data_plane_ok
curl -sf http://127.0.0.1:8790/health/full >/dev/null && echo orchestrator_ok
```

Starts data-plane, orchestrator, and `outbox-processor` (drains `tarka_outbox`). Consumer durable is `decision-worker`. Do not run a second consumer on that durable.

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
| **evaluate** | postgres, redis, core-api, frontend | Hot path. Page this box. Add signal-api only when that plane is on. |
| **graph** (optional) | Janus/Gremlin + graph-service | Isolate Gremlin heap from evaluate p95. |
| **forensics** (optional) | shadow_agent + Ollama | Isolate model weights. Outage ≠ deny. |

Do not put Janus + Ollama + evaluate on one VM and call it production.

---

## Health and ports (evaluate-only)

| Check | URL |
|-------|-----|
| Decision health | `GET http://<host>:8000/decisions/v1/health` |
| Decision ready | `GET http://<host>:8000/decisions/v1/ready` |
| Frontend | `GET http://<host>:3000/` |
| Signal API (signals overlay) | `GET http://<host>:8004/v1/health` |
| Investigation (investigation overlay) | `GET http://<host>:8006/v1/ready` |
| Graph (profile on) | `GET http://<host>:8001/v1/health` |
| Data-plane (ingest profile) | `GET http://<host>:8007/v1/health` |
| Orchestrator (ingest profile) | `GET http://<host>:8790/health/full` |

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
