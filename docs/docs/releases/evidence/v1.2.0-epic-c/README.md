# v1.2.0 Epic C release evidence bundle

**Deadline:** 2026-05-30 · **Gates:** [counter-replay-parity.md](../../guides/counter-replay-parity.md#epic-c-release-candidate-gate-criteria)

## How to populate

```bash
export AGG_KEY_VERSION=rc_parity_v1   # match staging/prod after cutover
export EVIDENCE_DIR="$(pwd)"
bash ../../../scripts/release/run_epic_c_rc_gates.sh
```

## Required attachments

| Gate | File / artifact |
|------|-----------------|
| C-1 | `rc-sha.txt` — output of `git rev-parse HEAD` |
| C-2 | `staging-agg-key-version-cutover.log` — **blocker** — full terminal log from [redis-agg-key-version-migration.md](../../guides/redis-agg-key-version-migration.md) |
| C-3a | `manual-parity-runbook.log` or section in `rc-gates-*.log` |
| C-3b | GitHub Actions run URL for **Counter parity smoke** on RC SHA |
| C-3c | Pytest log in `rc-gates-*.log` or CI decision-api job URL |
| C-4 | Day 60 window table in `rc-gates-*.log` or `day60-velocity-parity.json` |
| C-5 | Link to compose `AGG_KEY_VERSION` + [velocity-counter-rule-keys.md](../../guides/examples/velocity-counter-rule-keys.md) |

## Sign-off checklist

- [ ] C-2 Platform/SRE + Release Manager
- [ ] C-3a–c Data Engineering + Release Manager
- [ ] C-4 Data Engineering
- [ ] C-5 Platform Engineering
