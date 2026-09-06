# GitLab-shaped product P0 (P-day1)

**Date:** 2026-09-06  
**Status:** Design locked in chat (`go`).  
**Branch:** `honesty/gitlab-shaped-product-p0` stacked on P-left1 (`#384` / `honesty/leftover-first-class`)  
**Related:** leftover env gates (P-left1), desk profiles (P-reg1), `make demo`

## Goal

Named-desk defaults live in `desk_provision.json` for the first time. `make product` is the product skin + that file. Demo compose stays demo. Webhooks wait for P-enf1.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty plane URL = that plane off.
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`.
- Demo ≠ product. Visual builder stays `RequireRole` RiskArchitect.
- `desk_provision.json` first appears in this PR.
- Env overrides the file when set (`TARKA_*`, `GRAPH_SERVICE_URL`, plane URLs).
- `brochure` stays the env token. Published copy says **sales-only overlay**.
- No Tarka OSS / third-party desk names in new copy. Keep `scripts/oss/` path names.
- Helm prod-on-k8s stays frontend OFF and Shadow OFF in the chart. Product compose may start `shadow_agent` only when an LLM URL is set.

## File

`infra/deploy/desk_provision.schema.json` + `infra/deploy/desk_provision.example.json`

| Key | Meaning |
|-----|---------|
| `schema_id` | `tarka.desk_provision/v1` |
| `profile` | `demo` \| `product` \| `brochure` |
| `hunt.enabled` | default true. Hunt off only if this is false **and** no env override |
| `graph.service_url` | empty = hop off |
| `leftover.flag_mints_leftover` | default false |
| `leftover.multi_analyst_claim` | default false |
| `leftover.qa_queue_isolates` | default false |
| `leftover.receipt_brief_enabled` | default false |
| `shadow_agent.start_when_llm_url` | product true; demo compose ignores |

Missing file = today’s env defaults. Invalid `schema_id` → ignore file (log once), env-only.

## Reader

`services/shared/desk_provision.py`

- Path: `TARKA_DESK_PROVISION_PATH` (Helm `/etc/tarka/desk_provision.json`).
- `leftover_flag(env_name, provision_key)` — nonempty env wins, else file, else false.
- `hunt_enabled()` — `TARKA_HUNT_ENABLED` if set, else file `hunt.enabled` (default true).
- `graph_service_url()` — `GRAPH_SERVICE_URL` if the env key is present (empty = off), else file `graph.service_url`.
- `shadow_agent_should_start()` — false on demo profile; else file `start_when_llm_url` (default true) and a nonempty LLM URL.

Leftover helpers and `Settings.flag_mints_leftover` call the reader. Import miss falls back to env-only.

## Product vs demo

| Path | Skin | Provision | `shadow_agent` |
|------|------|-----------|----------------|
| `make demo` | `VITE_DESK_PROFILE=demo` | none required | never |
| `make product` | `VITE_DESK_PROFILE=product` + example file | mounted | only when `OPENAI_BASE_URL` (or peer) is set |

`make demo` / `docker-compose.fraud-desk.yml` unchanged.

## Helm

ConfigMap of the example file. Mount on core-api at `/etc/tarka/desk_provision.json`. `TARKA_DESK_PROVISION_PATH` set. Chart still does not start a desk or Shadow.

## Docs

README: demo vs product vs sales-only. P0 limitation table (no provisioned webhooks, no Postgres notify, Helm Shadow OFF, `brochure` token unchanged). clone-demo: `make product` exists; sales-only overlay, not brochure as the product name.

## Non-goals

- P-enf1 webhooks / notify / allow hooks.
- Renaming `VITE_DESK_PROFILE=brochure`.
- New leftover table.
- Starting Shadow on `make demo`.

## Done when

On a branch stacked on `#384`: schema + example exist; loader tests cover missing file, bad schema, env-wins, leftover defaults; leftover env helpers read the file; Helm mounts the file; `make product` starts the product skin; demo path unchanged; README names three skins and P0 limits.
