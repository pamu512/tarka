# Paste-ready GitHub comments: close epics #4–#12

Use these **as the closing comment** when you mark each issue closed (this environment cannot call the GitHub Issues API).

**Integration branch:** `ide/v1.2.5-7320`  
**Merge PR:** https://github.com/pamu512/tarka/pull/98  
**Reference commits:** tip of `origin/ide/v1.2.5-7320` (example tip: `4800730` — includes integrity `tag_rules` / `signal_tags` for **#6**, CI lint fixes, and closure-comment doc).

---

## #4 — Epic B: SDK request envelope signing

```text
**Closing — acceptance criteria met.**

- Canonical HMAC: `services/shared/tarka_request_signature.py` (`X-Tarka-Timestamp`, `X-Tarka-Signature`; message = `timestamp\n` + raw body bytes).
- Python SDK helpers + tests: `packages/fraud-sdk-python/src/fraud_stack_sdk/request_signing.py`, `packages/fraud-sdk-python/tests/test_request_signing.py`.
- Optional gateway enforcement: `services/decision-api/src/decision_api/request_signature_middleware.py`.

Evidence: `ide/v1.2.5-7320` (see PR #98).
```

---

## #5 — Epic B: Replay detection at decision ingress

```text
**Closing — acceptance criteria met.**

- Redis replay window: `RedisTagStore.check_and_store_replay_signature` in `services/decision-api/src/decision_api/redis_store.py`.
- Evaluate path: payload signature, `ingress:replay_payload` on duplicate window, `replay_rule_hits` merged into audit/rule output — `services/decision-api/src/decision_api/main.py`.
- Tests mock the replay store (e.g. `services/decision-api/tests/test_openapi_contract_files.py` and related evaluate tests).

Evidence: `ide/v1.2.5-7320` (PR #98).
```

---

## #6 — Epic B: Tamper mismatch reasons and policy actions

```text
**Closing — acceptance criteria met.**

- **Stable tags / surfaces:** `ingress:replay_payload`, geo mismatch tags (`sdk:geo_ip_mismatch`, `sdk:geo_tz_mismatch`), device integrity markers; release notes cross-ref: `docs/docs/releases/v1.1.0-2026-04-30.md`.
- **Policy-as-code JSON:** `services/decision-api/rules/integrity_tamper_policy_v1.json` — `tag_rules` escalate on replay, geo mismatch, emulator/repackaged.
- **Rule engine:** `evaluate_json_rules(..., signal_tags=...)` merges request-scoped tags with Redis tags so `tag_rules` match ingress/geo/integrity without persisting every tag to Redis — `services/decision-api/src/decision_api/json_rules.py`; evaluate passes `signal_tags` from `main.py`. Integrity supplements run before JSON rule evaluation.
- **Tests:** `services/decision-api/tests/test_json_rules.py` (`test_signal_tags_merge_for_tag_rules`).

Key commit (integrity policy + merge): `4b2267f` on `ide/v1.2.5-7320`.
```

---

## #7 — Epic C: Multi-window counter service (5m/1h/24h)

```text
**Closing — acceptance criteria met.**

- Aggregate-backed features `event_count_5m`, `event_count_1h`, `event_count_24h` (and extended windows where configured) from `AggregateStore` / `services/decision-api/src/decision_api/aggregates.py`, injected in evaluate (`services/decision-api/src/decision_api/main.py`).
- Consumed by JSON rules (`services/decision-api/rules/velocity_rules.json`) and inference (`services/decision-api/src/decision_api/inference_build.py`).

Evidence: `ide/v1.2.5-7320` (PR #98).
```

---

## #8 — Epic C: Normalized velocity feature keys for rules and ML

```text
**Closing — acceptance criteria met.**

- Versioned catalog: `services/decision-api/src/decision_api/data/counter_catalog.json` (and Ops Counters / governance surfaces).
- Same keys feed JSON rules, ML feature payloads, and inference context (e.g. `event_count_*`, distinct IP/device windows).

Evidence: `ide/v1.2.5-7320` (PR #98).
```

---

## #9 — Epic C: Historical replay utility for counters

```text
**Closing — acceptance criteria met.**

- Scripts: `scripts/replay/replay_aggregates.py`, `scripts/replay/export_audit_to_jsonl.py`, `scripts/replay/run_offline_parity.py`; docs `scripts/replay/README.md`, `docs/docs/guides/counter-replay-parity.md`, `docs/docs/guides/ingest-replay-onboarding.md`.
- CI parity: `.github/workflows/counter-parity-smoke.yml` (replay fixture twice, diff Redis).

Evidence: `ide/v1.2.5-7320` (PR #98).
```

---

## #10 — Epic D/E: Challenge orchestration and location coherence

```text
**Closing — acceptance criteria met.**

- Challenge templates / escalation: `services/decision-api/src/decision_api/challenge_policy.py`, JSON under `services/decision-api/rules/challenge_policies/`, tests `services/decision-api/tests/test_challenge_policy.py`.
- Location coherence: `services/decision-api/src/decision_api/location_context.py`, geo tags + `services/decision-api/src/decision_api/inference_build.py` (confidence tiers, recommended actions); tests e.g. `services/decision-api/tests/test_location_context.py`, `services/decision-api/tests/test_inference_build.py`.

Evidence: `ide/v1.2.5-7320` (PR #98).
```

---

## #12 — Epic F: Outcome-to-label ingestion and KPI overlays

```text
**Closing — acceptance criteria met.**

- **Outcome → ML label:** dispute resolution posts training feedback to ML — `services/case-api/src/case_api/dispute_api.py` (`_send_ml_feedback` → `POST {ml_scoring}/v1/feedback` with label from outcome).
- **Analyst / ops surfaces:** case + dispute flows in frontend; calibration / governance endpoints documented in `docs/docs/releases/v1.1.0-2026-04-30.md` (`/v1/ops/calibration-status`, `/v1/ops/governance`).

Evidence: `ide/v1.2.5-7320` (PR #98).
```

---

*After pasting, close each issue with the GitHub UI “Close issue” button.*
