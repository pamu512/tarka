# Thin-fix Waves 4–6

**Date:** 2026-08-04  
**Status:** Implemented (branch `feat/ops-golden-holdout`; Waves 4–6)

## Wave 4 — SR-16 sanctions explain + JSONL mirror
- Enrich match explain: matched_name, score, threshold, country/dob dampen, cache mtime/age, screening_log_id
- After successful Postgres insert, append JSONL under `SANCTIONS_SCREENING_JOURNAL_PATH` (default under sanctions cache dir); fail soft on journal
- Postgres remains SoR / fail-closed; update STUB_REGISTER

## Wave 5 — SR-15 durable rule telemetry
- Dual-write: process memory + Redis `HINCRBY` when reachable
- `GET /v1/rules/telemetry` prefers Redis → `durability: "redis"`; else process_memory labels
- `RULE_HIT_TELEMETRY_REDIS=0` forces memory-only

## Wave 6 — SR-17 honesty + SR-13 shrink slice
- SR-17: expose `durability: "disk_ttl"` on batch ingest; register Done
- SR-13: migrate ≥3 pages off god `client.ts` barrel onto `api/v1/*`

## Out of scope
Matcher rewrite, ClickHouse telemetry, full mock purge, FinCEN XSD
