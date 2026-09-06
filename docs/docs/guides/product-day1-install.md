# Product Day-1 install

**Goal:** Bring up the **product** desk (`make product`) or mount `desk_provision.json` on Helm without mixing those two shapes into one lie.

Tarka application code is **source-available** under Elastic License 2.0 (not open-source). Self-hosting on your own metal or VPC for your own operations is allowed; providing Tarka to third parties as a hosted or managed service is not.

Demo first-hour path stays [`make demo`](./clone-demo.md). This page is the product / named-desk path.

## Skins (do not smash)

| Skin | How | What you get |
|------|-----|----------------|
| **Demo** | `make demo` | First-hour pages. `VITE_DESK_PROFILE=demo`. No `desk_provision` required. No `shadow_agent`. |
| **Product** | `make product` | Analyst jobs (visual / backtest / lists / simulation / analytics) + `infra/deploy/desk_provision.example.json` mounted. `shadow_agent` only when `OPENAI_BASE_URL` is set (`--profile llm`). |
| **Sales-only overlay** | `VITE_DESK_PROFILE=brochure` / `VITE_LEAN_NAV=false` | Pitch pages. Not the product default. The env token stays `brochure`. |

## Command

```bash
make doctor && make product
```

Same script: `bash scripts/oss/up_product.sh`. Compose files: `docker-compose.lite.yml` + `docker-compose.fraud-desk.yml` + `docker-compose.product.yml`.

`make doctor` checks Docker Desktop (Compose v2), ports `8000` `8001` `3000` `5432` `6379`, and ~4 GB RAM. First build is the long pole.

After PASS, Hunt is home when graph is on (`NEXT:` URL + `entity_id`). Receipts stay at `http://127.0.0.1:3000/decisions`. Leftovers at `/leftovers`. Observe at `/ops/shadow`. Visual builder is a **product-desk** job at `/rules/visual` (`RequireRole` RiskArchitect).

## `desk_provision.json`

Mounted on core-api as `TARKA_DESK_PROVISION_PATH=/etc/tarka/desk_provision.json`. Schema: `infra/deploy/desk_provision.schema.json`. Example: `infra/deploy/desk_provision.example.json`.

Nonempty `TARKA_*` / plane URLs win over the file. Missing file = env defaults.

| Key | Default | Meaning |
|-----|---------|---------|
| `leftover.flag_mints_leftover` | false | FLAG may mint a leftover |
| `leftover.multi_analyst_claim` | false | Second analyst may overwrite claim |
| `leftover.qa_queue_isolates` | false | `qa:pending` drops off the leftover list |
| `leftover.receipt_brief_enabled` | false | Leftover JSON may include `receipt_brief` |
| auto-promote | off | First-review checkbox on `/ops/shadow`. Named-desk `observe.auto_promote` / `TARKA_AUTO_PROMOTE` when that reader is on the build. |
| `hunt.enabled` | true | Loader Hunt-off. Desk chrome matches after bake (`VITE_HUNT_ENABLED=0` or empty `VITE_GRAPH_SERVICE_URL`). |
| `hooks.enforcement.url` | empty | Empty = webhook off |
| `hooks.observe_notify.url` | empty | Empty = webhook off |
| `hooks.*.secret_env` | `TARKA_*_WEBHOOK_SECRET` | Secret **name**, never the secret |

## Webhooks and observe inbox

Secrets live in env, not in the JSON file.

- Set `hooks.enforcement.url` or `TARKA_ENFORCEMENT_WEBHOOK_URL`. Allow evaluate may POST `tarka.enforcement/v1` when a URL is set. No-reach = no webhook.
- Set `hooks.observe_notify.url` or `TARKA_OBSERVE_NOTIFY_WEBHOOK_URL`. Envelope `tarka.observe_notify/v1`.
- Product observe inbox: Postgres table `observe_notify` when `TARKA_OBSERVE_NOTIFY_STORE=postgres` or provision `profile=product`. Demo may keep the jsonl file.

Webhook 5xx does not block evaluate or Promote.

## Limitation table 1 — product desk (`make product`)

What the **product compose desk** actually runs. Aligns with VISION: graph is required for the desk.

| On | Off / thin |
|----|------------|
| Lite AGE + `graph-service` + Hunt (`VITE_GRAPH_SERVICE_URL=/api/graph`) | Empty graph URL = Hunt hidden, home `/decisions` (evaluate-only fallback, not this skin) |
| Visual / backtest / lists / simulation / analytics | Demo-only first-hour hide; sales-only brochure pages |
| `desk_provision.example.json` on core-api | Leftover CRM verbs default **off** |
| Observe `/ops/shadow` | Auto-promote default **off** (first-review; named-desk gate when present) |
| `shadow_agent` | Only if `OPENAI_BASE_URL` is set |
| Enforcement / observe-notify hooks | Empty URL = off |

Hunt-off on this desk: empty `VITE_GRAPH_SERVICE_URL` **or** `TARKA_HUNT_ENABLED=0` (rebuild). `hunt.enabled: false` in the file turns the loader off; chrome matches after that bake.

## Limitation table 2 — Helm (`prod-on-k8s` / `evaluate-only`)

Do **not** treat these as `make product`. Chart `values.yaml` defaults `graphService.enabled: false`. Presets change the shape.

| Preset | Desk | Graph | Shadow / Advise | Notes |
|--------|------|-------|-----------------|-------|
| **prod-on-k8s** | frontend **OFF** | not the product desk | Shadow **OFF** | core-api HA. `desk_provision` ConfigMap still mounts on core-api. No Hunt glass. |
| **evaluate-only** | frontend **ON** | `graphService` **OFF** | investigation **OFF** | Evaluate-shaped cluster + a frontend. Not lite compose (lite compose still has AGE + graph-service). Hunt hidden unless you bake a graph URL. |
| **lite-on-k8s** | frontend **OFF** | not Hunt glass | investigation **ON** | Not evaluate-only. Not `make product`. |

Helm `deskProvision.enabled` writes a ConfigMap (`schema_id` `tarka.desk_provision/v1`) and sets `TARKA_DESK_PROVISION_PATH`. Env still wins. Empty hook URLs stay off.

```bash
helm install tarka infra/deploy/helm/fraud-stack \
  -f infra/deploy/helm/fraud-stack/values.yaml \
  -f infra/deploy/helm/fraud-stack/presets/evaluate-only.yaml
```

prod-on-k8s is a separate HA overlay. It is not this evaluate-only shape and it is not `make product`.

## What this page does not promise

- SLA / uptime.
- evaluate-only === lite compose.
- Helm prod-on-k8s === product desk.
- Auto-promote, FLAG leftover mint, or webhooks on by default.
