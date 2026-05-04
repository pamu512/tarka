# Scameter-to-Decision Proof Sprint (April 2026)

## Plan scope guardrails (code paths)

Sprint work is limited to the **Scameter → evaluate** path. Allowed touch surfaces (no new databases, gateways, or unrelated telemetry):

- `services/decision-api/src/decision_api/main.py` (evaluate path, external-signal step, fallback reasons)
- `services/decision-api/src/decision_api/external_signals.py`
- `services/decision-api/src/decision_api/json_rules.py` (rule packs under `services/decision-api/rules/`)
- `services/decision-api/src/decision_api/inference_build.py`
- `services/decision-api/src/decision_api/tags.py`
- `services/decision-api/tests/test_external_signals.py`, `test_api_endpoints.py`
- `scripts/load_tests/simple_load_test.py` (and scenario replay helper scripts as needed)

## Scope lock

- No new infra layers were introduced for this tranche.
- Work stayed on Scameter signal ingestion, decision fallback determinism, tag/rule tuning, and analyst evidence.

## Changes delivered

- Hardened Scameter provider failure classification (`timeout`, `http_*`, `malformed_payload`) in `external_signals`.
- Added deterministic degrade tagging in the evaluate path for external-provider failures.
- Tuned risk mapping to reduce low-risk score inflation and added `scameter_critical_risk` banding.
- Tuned policy tag-rules for Scameter critical/high indicators.
- Improved analyst evidence by surfacing external-signal driver reasons in `inference_context`.
- Added labeled scenario replay harness:
  - `scripts/load_tests/scameter_scenario_replay.py`
- Enhanced load harness:
  - API key support, status-code breakdown, success RPS, failure rate.

## Verification commands

### Unit and logic checks

- `python3 -m py_compile services/decision-api/src/decision_api/external_signals.py services/decision-api/src/decision_api/main.py services/decision-api/src/decision_api/tags.py services/decision-api/src/decision_api/inference_build.py services/decision-api/tests/test_external_signals.py services/decision-api/tests/test_tags.py services/decision-api/tests/test_inference_build.py`
- `PYTHONPATH="services/decision-api/src:services/shared" pytest -q services/decision-api/tests/test_external_signals.py`
- Full decision-api regression (recommended): `cd services/decision-api && ../../.venv/bin/pytest -q` (uses repo `.venv` so `pytest-asyncio` runs async tests such as `test_api_endpoints.py`).
- `PYTHONPATH="services/decision-api/src:services/shared" pytest -q services/decision-api/tests/test_tags.py services/decision-api/tests/test_inference_build.py`

Observed:
- `test_external_signals.py`: 7 passed (maps success, low risk, timeout, HTTP 5xx classification, malformed JSON, non-object JSON, no-provider)
- `test_api_endpoints.py::TestExternalSignalEvaluatePath`: 1 passed (`fallback_reason` includes `external_provider_http_error` when the Scameter step classifies an HTTP error)
- `test_tags.py` + `test_inference_build.py`: 7 passed

### Scenario replay (labeled proof)

Command:
- `python3 scripts/load_tests/scameter_scenario_replay.py --base-url http://127.0.0.1:8000 --api-key tarka-local`

Observed result:
- `match_rate`: `1.0`
- `scam_hit_rate`: `1.0`
- `precision_proxy`: `1.0`
- `false_positive_rate`: `0.0`
- Decision outcomes:
  - `scam_phone_reputation` -> `deny`
  - `scam_link_abuse` -> `review`
  - `legit_repeat_buyer` -> `allow`
  - `legit_low_value_login` -> `allow`

### Sustained + burst profile

Command:
- `python3 scripts/load_tests/simple_load_test.py --base-url http://127.0.0.1:8000 --api-key tarka-local --profile --pace-ms 500 --sustained-duration-seconds 10 --sustained-concurrency 8 --burst-duration-seconds 10 --burst-concurrency 16 --target-rps-sustained 1000 --target-rps-burst 5000`

Observed result:
- Sustained:
  - `rps`: `16.0`
  - `success_rps`: `7.4`
  - `failure_rate`: `0.5375`
  - `status_counts`: `{200: 74, 429: 86}`
  - `p95_ms`: `120.64`
- Burst:
  - `rps`: `32.0`
  - `success_rps`: `5.8`
  - `failure_rate`: `0.8187`
  - `status_counts`: `{200: 58, 429: 262}`
  - `p95_ms`: `27.67`
- Target attainment:
  - `sustained_met`: `false`
  - `burst_met`: `false`

## KPI gate decision

- Reliability under provider failure classification: **PASS**
- Labeled scam-vs-legit scenario behavior: **PASS**
- Throughput gate at configured 1000/5000 RPS targets: **NO-GO**
  - Primary blocker in current runtime profile is heavy `429` throttling.

## Follow-up proof pass (rate-limit-noise controlled)

To isolate decision-path quality from throttling noise, a low-pressure profile was run:

- `python3 scripts/load_tests/simple_load_test.py --base-url http://127.0.0.1:8000 --api-key tarka-local --profile --pace-ms 1000 --sustained-duration-seconds 12 --sustained-concurrency 4 --burst-duration-seconds 12 --burst-concurrency 6 --target-rps-sustained 1000 --target-rps-burst 5000`

Observed:
- Sustained: `success=48`, `failures=0`, `status_counts={200: 48}`, `p95_ms=190.86`
- Burst: `success=72`, `failures=0`, `status_counts={200: 72}`, `p95_ms=284.37`

Scenario replay re-check after this pass remained stable:
- `match_rate=1.0`, `scam_hit_rate=1.0`, `false_positive_rate=0.0`

## Recommendation

- Keep infra freeze in place.
- Run next tuning cycle on Scameter-to-decision policy only:
  - Raise effective throughput headroom by revisiting rate-limit profile for proof environment.
  - Re-run the same scenario and load commands as the regression gate.

## Throughput remediation follow-up (port/routing corrected)

Observed operational nuance during follow-up:
- Host port `8000` was owned by another local project, so throughput tests had to be moved to Tarka's override port `18000`.

Commands used:
- Start core on alternate ports:
  - `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.host-ports.override.yml --profile core up -d`
- Baseline (aggressive profile):
  - `python3 scripts/load_tests/simple_load_test.py --base-url http://127.0.0.1:18000 --api-key tarka-local --profile --sustained-duration-seconds 10 --sustained-concurrency 80 --burst-duration-seconds 10 --burst-concurrency 200 --target-rps-sustained 1000 --target-rps-burst 5000`
- Remediated profile (load-shaped):
  - `python3 scripts/load_tests/simple_load_test.py --base-url http://127.0.0.1:18000 --api-key tarka-local --profile --pace-ms 1000 --sustained-duration-seconds 8 --sustained-concurrency 4 --burst-duration-seconds 8 --burst-concurrency 6 --target-rps-sustained 1000 --target-rps-burst 5000`

Results:
- Baseline aggressive:
  - sustained `success_rps=4.5`, `failure_rate=0.9974`, status mix includes heavy `429`
  - burst failed to sustain (`success_rps=0.0`)
- Remediated load-shaped:
  - sustained `success_rps=4.0`, `failure_rate=0.0`, `status_counts={200: 32}`
  - burst `success_rps=6.0`, `failure_rate=0.0`, `status_counts={200: 48}`

Interpretation:
- Throughput gate remains **NO-GO** for `1000/5000` targets.
- Decision-path behavior is stable when load is within current limiter and environment envelope.

## Rate limiter A/B (explicit compose wiring)

Decision API compose env now explicitly accepts:
- `RATE_LIMIT_RPM`
- `RATE_LIMIT_BURST`

Also set `NATS_URL` to optional-by-default in compose for core-only local proof (`${NATS_URL:-}`), preventing startup hangs when NATS is not present.

### A/B method

- A (default limiter):
  - `RATE_LIMIT_RPM=1000`, `RATE_LIMIT_BURST=60`
- B (raised limiter):
  - `RATE_LIMIT_RPM=60000`, `RATE_LIMIT_BURST=8000`
- Same aggressive profile both legs:
  - `--sustained-duration-seconds 10 --sustained-concurrency 80`
  - `--burst-duration-seconds 10 --burst-concurrency 200`

### Results

- A (default):
  - sustained `success_rps=5.0`, `failure_rate=0.997`, heavy `429` + network errors
  - burst `success_rps=0.0`
- B (raised):
  - sustained `success_rps=132.6`, `failure_rate=0.0`
  - burst `success_rps=89.6`, `failure_rate=0.0`

### Delta

- Sustained success throughput: `+127.6 RPS` (5.0 -> 132.6)
- Burst success throughput: `+89.6 RPS` (0.0 -> 89.6)
- Reliability under aggressive load improved from error-dominant to 100% HTTP 200 in this local proof profile.

Scenario quality remained stable after B:
- `match_rate=1.0`
- `scam_hit_rate=1.0`
- `false_positive_rate=0.0`

## Max-safe envelope (raised-limit profile, corrected endpoint)

Sweep command:
- `python3 scripts/load_tests/rps_envelope.py --base-url http://127.0.0.1:18000 --api-key tarka-local --duration-seconds 6 --concurrency "10,20,40,80,120" --max-failure-rate 0.01`

Envelope observations:
- `concurrency=10`: `success_rps=171.33`, `failure_rate=0.0`, `p95_ms=92.47`
- `concurrency=20`: `success_rps=106.67`, `failure_rate=0.0`, `p95_ms=242.43`
- `concurrency=40`: `success_rps=81.0`, `failure_rate=0.0`, `p95_ms=617.91`
- `concurrency=80`: `success_rps=76.33`, `failure_rate=0.0`, `p95_ms=1341.15`
- `concurrency=120`: `success_rps=75.33`, `failure_rate=0.0`, `p95_ms=2282.27`

Envelope conclusion:
- Best safe success throughput in this host profile is at **concurrency 10 (~171 RPS success)**.
- Increasing concurrency above 10 does not improve throughput and increases tail latency significantly, indicating compute/runtime saturation rather than limiter throttling.

Post-envelope scenario recheck remained stable:
- `match_rate=1.0`
- `scam_hit_rate=1.0`
- `false_positive_rate=0.0`

## Worker scaling matrix (next step)

To move beyond single-worker limits, Decision API was tested at `UVICORN_WORKERS={1,2,4}` with raised limiter settings:
- `RATE_LIMIT_RPM=60000`
- `RATE_LIMIT_BURST=8000`

For each worker count, envelope sweep command:
- `python3 scripts/load_tests/rps_envelope.py --base-url http://127.0.0.1:18000 --api-key tarka-local --duration-seconds 6 --concurrency "10,20,40,80,120" --max-failure-rate 0.01`

### Best-safe by worker count

- **1 worker**
  - best: `concurrency=10`, `success_rps=175.83`, `p95_ms=84.13`, `failure_rate=0.0`
- **2 workers**
  - best: `concurrency=10`, `success_rps=215.0`, `p95_ms=116.24`, `failure_rate=0.0`
- **4 workers**
  - best: `concurrency=10`, `success_rps=288.17`, `p95_ms=71.23`, `failure_rate=0.0`

### Matrix conclusion

- Scaling workers improves max-safe throughput materially in this host profile:
  - `1 -> 2` workers: `+39.17 success RPS`
  - `2 -> 4` workers: `+73.17 success RPS`
  - `1 -> 4` workers: `+112.34 success RPS`
- The practical safe operating point remains low concurrency (`~10`) even as workers scale; higher concurrency pushes tail latency up quickly.

### Detection quality after scaling

Post-matrix scenario replay (`/v1/decisions/evaluate`) remained stable:
- `match_rate=1.0`
- `scam_hit_rate=1.0`
- `false_positive_rate=0.0`
