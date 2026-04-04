# Release Calendar - May 2026

This one-page calendar mirrors the scheduled Friday release queue for May 2026.

## v1.1.0 on 2026-04-30 (ahead of this calendar)

The following themes were **folded into `v1.1.0` (`2026-04-30`)** as a single ship (see `docs/docs/releases/v1.1.0-2026-04-30.md`):

- Decision API **`inference_context` v2** (tier, drivers, velocity 5m/1h/24h, colocation / travel proxies, replay-tamper signals).
- **`recommended_action`** on evaluate and audit.
- OpenAPI + **Python / TypeScript SDK** parity for the above.
- **Frontend** Case Detail explainability + mock API v2 payloads.
- **Simulation** `experiment_guardrails` on `/v1/simulation/run`.

The May rows below are **incremental follow-ups** after 4/30 (docs, competitive matrix, or additional hardening)—not duplicates of the 4/30 payload unless the queue file is updated.

## Planned Friday Releases

| Date       | Week Label  | Commit  | Focus |
|------------|-------------|---------|-------|
| 2026-05-01 | may-week-1  | `61afd59` | Post–v1.1.0 hardening or docs-only (queue TBD if scope empty) |
| 2026-05-08 | may-week-2  | `4ba1467` | Post–v1.1.0 hardening or docs-only (queue TBD) |
| 2026-05-15 | may-week-3  | `dab2d03` | Post–v1.1.0 hardening or docs-only (queue TBD) |
| 2026-05-22 | may-week-4  | `e33b34c` | Post–v1.1.0 hardening or docs-only (queue TBD) |
| 2026-05-29 | may-week-5  | `a26d1cc` | Competitive score matrix and epic-aligned roadmap documentation |

## Source of Truth

- Queue file: `scripts/release/release-queue-2026-05.json`
- Task setup script: `scripts/release/setup-friday-release-tasks-2026-05.ps1`
- Queue runner: `scripts/release/push-queued-commit.ps1`

## Operational Notes

- Scheduled tasks are configured for Fridays at `09:00` local time.
- Each release pushes a specific commit to `origin/master` based on the queue entry for that date.
- If no queue entry exists for a date, the runner exits without changes.
