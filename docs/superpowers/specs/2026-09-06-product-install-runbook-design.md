# Product install runbook (G-run1)

**Date:** 2026-09-06  
**Status:** Design locked in gap plan (`keep going`).  
**Branch:** `docs/product-install-runbook` from `origin/master`  
**Related:** `make product`, `desk_provision.json`, P-enf1 hooks, Helm presets

## Goal

One operator guide for `make product` / Helm-mounted `desk_provision`, Postgres observe notify, and webhooks via `secret_env`. Two limitation tables (product desk vs Helm evaluate-only / prod-on-k8s). No smashed lie.

## Locked

- Demo ≠ product ≠ sales-only overlay (`brochure` token unchanged).
- Do not promise SLA. Do not invent customers. Do not claim evaluate-only === lite compose.
- Helm prod-on-k8s: frontend OFF, Shadow OFF. evaluate-only: graph-service OFF, frontend ON (evaluate-shaped desk).
- Product compose: Hunt on Day-1 (AGE + `/api/graph`). Visual builder is a product-desk job.
- No third-party desk names. Do not call Tarka OSS.
- Empty hook URL = that webhook off. Secrets never in the JSON file.

## Non-goals

- Re-writing G-doc1 leftover tours.
- Changing compose or Helm values.

## Done when

`docs/docs/guides/product-day1-install.md` exists; README + INDEX + mkdocs link it; two tables do not contradict VISION vs Helm.
