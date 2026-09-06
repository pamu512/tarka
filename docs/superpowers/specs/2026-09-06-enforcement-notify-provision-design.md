# Provisioned webhooks + Postgres observe notify (P-enf1)

**Date:** 2026-09-06  
**Status:** Design locked in chat (`go`).  
**Branch:** `honesty/enforcement-notify-provision` stacked on P-day1 (`#385` / `honesty/gitlab-shaped-product-p0`)  
**Related:** `desk_provision.py`, `enforcement.py`, `observe_notify.py`

## Goal

Enforcement and observe-notify webhook URLs live in `desk_provision` (env wins). Every evaluate that reached Tarka can emit the return webhook, including allow. Product observe inbox survives restart in Postgres. Demo may keep the jsonl file.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty plane / hook URL = that sink off.
- Observe inbox → Postgres on product. Demo keeps jsonl unless `TARKA_OBSERVE_NOTIFY_STORE=postgres`.
- Hooks: `hooks.enforcement` / `hooks.observe_notify` with `url` + `secret_env`. Secrets never in the file.
- Slack/email = point those URLs at their incoming webhook. No first-party Slack.
- No `LISTEN/NOTIFY`. Enforcement journal stays jsonl. No `friction_tier`.
- `enforcement_action` is the act verb (`allow` / `step_up` / `block`). One risk `score`.
- No Tarka OSS / third-party desk names. Keep `scripts/oss/` paths.
- `make demo` unchanged.

## Store

`TARKA_OBSERVE_NOTIFY_STORE=postgres|file` wins when set. Else provision `profile=product` → postgres, otherwise file.

Same row: `id`, `tenant_id`, `type`, `subject_id`, `title`, `body`, `href`, `created_at`, `read_at`. Dedup `(tenant_id, type, subject_id)`.

Postgres down → fail-soft log; list empty; evaluate still returns.

## Hooks

Nonempty `TARKA_ENFORCEMENT_WEBHOOK_URL` / `TARKA_OBSERVE_NOTIFY_WEBHOOK_URL` win. Else file URL. Secret from `TARKA_*_SECRET` if set, else the named `secret_env`.

Allow already fires when a URL is set. No-reach (evaluate never ran) = no webhook.

## Non-goals

LISTEN/NOTIFY. Journal → Postgres. First-party Slack/email. New score field.

## Done when

On a branch stacked on `#385`: hooks in schema/example; loader env-wins; allow webhook test; observe emit/list/mark_read on Postgres + file; docs say act verb + one score + no-reach; README no longer claims webhooks/notify are missing.
