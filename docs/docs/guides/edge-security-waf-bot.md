# Edge Security: WAF and Bot Signals

Tarka can ingest edge-layer WAF/bot decisions into decision tags and policy escalation.

## What this enables

- Edge action tags: `edge:waf_blocked`, `edge:waf_challenge`, `edge:waf_observed`
- Bot score tags: `edge:bot_score_block`, `edge:bot_score_review`, `edge:bot_score_ok`
- Automatic policy escalation via `integrity_tamper_policy_v1.json` tag rules:
  - `policy:edge_block_escalation`
  - `policy:edge_challenge_review`

## Runtime flags (decision-api)

Set these in `decision-api`:

- `EDGE_SECURITY_SIGNALS_ENABLED=true`
- `EDGE_WAF_ACTION_HEADER=<header-name>`
- `EDGE_BOT_SCORE_HEADER=<header-name>`
- `EDGE_BOT_SCORE_BLOCK_THRESHOLD=25`
- `EDGE_BOT_SCORE_REVIEW_THRESHOLD=50`

## Helm presets

Use preset overlays:

- `deploy/helm/fraud-stack/presets/edge-cloudflare.yaml`
- `deploy/helm/fraud-stack/presets/edge-aws-waf.yaml`

Example:

```bash
helm template tarka deploy/helm/fraud-stack \
  -f deploy/helm/fraud-stack/values.yaml \
  -f deploy/helm/fraud-stack/presets/edge-cloudflare.yaml
```

## Ops visibility

Use:

- `GET /v1/ops/edge-security-status`

This returns header config, thresholds, and edge signal counters from in-process metrics.
