# Pilot path: every plane, end to end

**Goal:** a named pilot desk running the full stack — not just the demo fraction — with
every plane verified alive and a known path to the product skin. Read
[clone-and-run desk](guides/clone-demo.md) first: this page is the continuation.

The stack ships as compose **planes**. `make demo` starts five services (postgres, redis,
graph-service, core-api, frontend) — evaluate, hunt, receipts, rules UI. Everything else
is opt-in per plane. None of it fails loudly when off; nginx just 503s the routes that
need it. This page is the honest map of what runs when, and how to verify each plane.

## Plane map

| Plane | Services | Activated by | Verified by |
|-------|----------|--------------|-------------|
| Desk core (evaluate/hunt/rules) | postgres (AGE), redis, graph-service, core-api, frontend | default | `GET :8000/decisions/v1/health`; `/decisions` receipts after a walk |
| Async ingest | nats, data-plane `:8007`, orchestrator `:8790`, outbox-processor | `--profile ingest` | `POST :8007/v1/events` → 202; receipts appear; outbox drains |
| Investigation copilot | investigation-agent `:8006` | `docker-compose.investigation.yml` | `curl :8006/v1/ready` |
| Signals / features / ML | nats, signal-api `:8004`, integration-ingress `:8003` | `docker-compose.signals.yml` | `curl :8004/v1/health` |
| Product skin (builder, backtest, entity lists, simulation) | frontend (`VITE_DESK_PROFILE=product`) | `make product` / `up_product.sh` | lean nav shows Rules/Builder entries |
| Rule-pack persistence | `desk_rules` named volume | default (lite + full) | `docker volume inspect desk_rules` — packs survive recreate |

RAM floors and per-plane details: [SRE Compose profiles](operations/sre-compose-profiles.md).

## The pilot sequence

1. **Desk core** — `make doctor && make demo`. Port conflicts: remap with `TARKA_*_PORT`
   in `infra/deploy/.env` (doctor names the variable). Health is
   `GET :8000/decisions/v1/health`, not merely "port 8000 answers".
2. **Async ingest** — `docker compose -f infra/deploy/docker-compose.lite.yml --profile ingest up -d --build`.
   Then `POST :8007/v1/events` (same `API_KEYS` as core-api; insecure local default is
   the same across all planes) and watch receipts land in `/decisions`. Default-compose
   caveat: the orchestrator rejects side-effect commits until `ORCHESTRATOR_INTERNAL_SECRET`
   is set on both data-plane and orchestrator (or `ALLOW_INSECURE_NO_AUTH=true` on the
   orchestrator) — until then events redeliver indefinitely instead of reaching
   audit/outbox. If events 202 but no receipts appear, the orchestrator/outbox leg is
   down — see [degraded operations](guides/degraded-operations.md).
3. **Signals (when the pilot needs features/ML)** — add `docker-compose.signals.yml`;
   desk picks up `VITE_SIGNAL_API_URL` automatically.
4. **Product skin** — `make product`: same APIs plus visual builder, backtest, entity
   lists, simulation, analytics (`desk_provision.example.json` mounted). Auto-Promote is
   off; promotion stays an analyst action.
5. **Authenticated REST alongside the UI** — set `API_KEYS` **and** `VITE_API_KEY`
   (the frontend bakes it at build; falls back to the first `API_KEYS` entry). Keys
   carry roles: viewer reads, analyst writes rules, admin for provisioning. See
   [rules auth](guides/rules.md#authentication-local-desk-vs-production).

## Known non-goals on a pilot box

- Auto-case on deny/review needs `CASE_INTERNAL_TOKEN` (shared with case-api). Empty
  token + enabled flag = startup ERROR in core-api logs; the lite default now ships a
  dev token so the desk works out of the box — set a real one before production.
- Helm's default render is evaluate-only (orchestrator off): events are acked but
  the async plane does not run. `orchestrator.enabled=true` deploys the full
  worker family (API, outbox-processor, shadow-investigate-worker, anumana
  duck-sink + heartbeat-monitor) and auto-wires data-plane's ORCHESTRATOR_URL.
  Compose `--profile ingest` remains the one-command pilot shape.
- Shadow evaluation streaming (JetStream `fraud.shadow.*`) runs only in the full
  compose flavor (shadow-investigate-worker consumes it into the shadow store);
  lite leaves core-api's `NATS_URL` empty by default. SAR FinCEN SFTP transport
  IS wired in lite — the worker runs inside core-api (DB-tick mode, no NATS
  needed); empty `FINCEN_BSA_SFTP_HOST` = feature off, queued intents fail
  honestly rather than silently.
