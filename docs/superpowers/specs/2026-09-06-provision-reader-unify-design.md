# Provision reader unify (G-prov1)

**Date:** 2026-09-06  
**Status:** Design locked in chat (`go`).  
**Branch:** `honesty/provision-reader-unify` from `origin/master` (`#386` tip)  
**Related:** `desk_provision.py` (P-day1 `#385`), leftover flags (P-left1 `#384`), shadow first-review file (`shadow_auto_promote.py`)

## Goal

Auto-promote and leftover switches resolve through `desk_provision.json`. `TARKA_*` wins. The legacy shadow provision file is not a second silent authority for those keys. Defaults stay thin (auto-promote **off**).

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty plane URL = that plane off.
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`.
- Demo ≠ product. Visual builder stays `RequireRole` RiskArchitect.
- Do not invent a second provision system. One reader: `services/shared/desk_provision.py`.
- Do not enable auto-promote by default (example file stays `false`).
- No CRM verbs. No new Slack/email sinks.
- No third-party desk / editor names in published copy. Do not call Tarka OSS.

## Already on master (do not reimplement)

Leftover FLAG mint / `multi_analyst_claim` / `qa_queue_isolates` / `receipt_brief_enabled` already go through `leftover_flag(env_name, provision_key)`. Case-api and `Settings.flag_mints_leftover` already call it. Caps stay on the legacy shadow JSON (`leftover_add_cap`, `leftover_fp_rate_cap`, `min_labeled_extras`).

## The gap

`maybe_auto_promote_shadow` enables when the tenant file `shadow_auto_promote_{token}.json` has `auto_promote: true`. That file is still a silent on-switch. First-review PUT on `/v1/rules/shadow-auto-promote-provision` writes it. Named-desk `desk_provision.json` has no `observe.auto_promote` key.

## Design

Add `observe.auto_promote` (default **false**) to the schema and example.

Env: `TARKA_AUTO_PROMOTE` — same truthy set as leftover (`1` / `true` / `yes` / `on`).

```
observe_auto_promote() -> bool | None
  nonempty TARKA_AUTO_PROMOTE → bool
  no valid desk_provision loaded → None   # file-only first-review (demo / tests)
  observe.auto_promote present → bool
  provision file present, key omitted → False
```

Tick / GET host truth:

```
host_auto_promote(file_flag) → False if observe_auto_promote() is False
                            → bool(file_flag) otherwise
```

Both must be on. File alone cannot enable when a named-desk file is mounted (or env is `0`). Loader alone cannot enable without first-review PUT. Env unset + no provision file → today's file-only behavior.

| Named (`observe_auto_promote`) | File `auto_promote` | Host tick / GET `auto_promote` |
|-------------------------------|---------------------|--------------------------------|
| `None` (no desk_provision)    | true                | true (compat)                  |
| `False` (file or env `0`)     | true                | false                          |
| `True` (env `1` or key true)  | false               | false (first review)           |
| `True`                        | true                | true                           |

GET `/v1/rules/shadow-auto-promote-provision` reports that AND so the desk checkbox does not lie. PUT still writes the file checkbox + caps. Caps stay on the legacy file.

Leftover keys: already on the loader. The shadow JSON is **not** leftover authority (`flag_mints_leftover` and peers are not read from it).

## Docs

Operator note on clone-demo / Observe: leftover switches and the auto-promote **boolean** live in `desk_provision` + `TARKA_*`. The legacy `tarka.shadow_auto_promote_provision/v1` file keeps first-review checkbox + leftover **caps** only.

## Non-goals

- Enable auto-promote in the example file.
- Move leftover caps onto `desk_provision`.
- CRM verbs, Slack/email sinks, a second provision system.
- Hunt chrome (`G-graph1`). Product install runbook (`G-run1`).

## Done when

`observe.auto_promote` exists and defaults false; env wins; tick no-ops when only the legacy file is true and named-desk is off; GET matches host truth; leftover flags stay on the loader; one PR.
