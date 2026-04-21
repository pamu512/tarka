#!/usr/bin/env python3
"""
Chaos smoke (R4.2): baseline recovery checks + optional dependency fallback matrix.

Manual / CI:
  python3 scripts/chaos/chaos_smoke.py
  python3 scripts/chaos/chaos_smoke.py --fault postgres
  python3 scripts/chaos/chaos_smoke.py --profile full --dependency-fallback-checks
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"
DECISION_HEALTH = "http://127.0.0.1:8000/v1/health"
EVALUATE_URL = "http://127.0.0.1:8000/v1/decisions/evaluate"
DEPENDENCY_FALLBACK_MATRIX = [
    ("graph-service", "step_graph_risk:http_error"),
    ("feature-service", "step_feature_snapshot:http_error"),
    ("ml-scoring", "step_ml_score:http_error"),
    ("counter-service", "step_counter_snapshot:http_error"),
    ("location-service", "step_location_eval:http_error"),
    ("calibration-service", "step_calibration:http_error"),
]


def compose_cmd(profile: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", profile]


def compose_up(profile: str) -> None:
    subprocess.run(
        compose_cmd(profile) + ["up", "-d", "--build"],
        cwd=REPO_ROOT,
        check=True,
    )


def compose_down(profile: str) -> None:
    subprocess.run(
        compose_cmd(profile) + ["down", "-v", "--remove-orphans"],
        cwd=REPO_ROOT,
        check=False,
    )


def compose_logs_tail(profile: str) -> None:
    subprocess.run(
        compose_cmd(profile) + ["logs", "--tail", "100"],
        cwd=REPO_ROOT,
        check=False,
    )


def compose_running_services(profile: str) -> set[str]:
    proc = subprocess.run(
        compose_cmd(profile) + ["ps", "--services", "--status", "running"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def compose_stop(profile: str, service: str) -> None:
    subprocess.run(
        compose_cmd(profile) + ["stop", service],
        cwd=REPO_ROOT,
        check=True,
    )


def compose_start(profile: str, service: str) -> None:
    subprocess.run(
        compose_cmd(profile) + ["start", service],
        cwd=REPO_ROOT,
        check=True,
    )


def probe_json_health(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, raw[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:400]
    except OSError as e:
        return -1, str(e)


def wait_decision_health_ok(deadline_seconds: float = 900.0, poll: float = 5.0) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        status, body = probe_json_health(DECISION_HEALTH)
        if status == 200:
            try:
                data = json.loads(body)
                if data.get("status") == "ok":
                    print(f"[ok] {DECISION_HEALTH}")
                    return
            except json.JSONDecodeError:
                pass
        print(f"[wait] decision-api health status={status} ({int(deadline - time.monotonic())}s left)")
        time.sleep(poll)
    raise TimeoutError("decision-api health did not become ok")


def smoke_evaluate_ok() -> None:
    """POST evaluate; require HTTP 200 and decision body."""
    payload = json.dumps(
        {
            "tenant_id": "chaos_smoke",
            "event_type": "login",
            "entity_id": "chaos-smoke-entity",
            "payload": {"source": "chaos_smoke", "amount": 50, "currency": "USD"},
        }
    ).encode()
    req = urllib.request.Request(
        EVALUATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            if resp.status != 200:
                raise RuntimeError(f"evaluate expected 200, got {resp.status}: {raw[:800]}")
            body = json.loads(raw)
            if "trace_id" not in body or "decision" not in body:
                raise RuntimeError(f"unexpected evaluate body: {raw[:800]}")
            print(f"[ok] POST {EVALUATE_URL} trace_id={body.get('trace_id')}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        raise RuntimeError(f"evaluate HTTP {e.code}: {raw[:800]}") from e


def evaluate_any_status() -> tuple[int, str]:
    """POST evaluate without asserting status (fault window observation)."""
    payload = json.dumps(
        {
            "tenant_id": "chaos_smoke",
            "event_type": "login",
            "entity_id": "chaos-smoke-entity",
            "payload": {"source": "chaos_smoke_fault", "amount": 50, "currency": "USD"},
        }
    ).encode()
    req = urllib.request.Request(
        EVALUATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode()[:800]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:800]
    except OSError as e:
        return -1, str(e)


def _extract_fallback_reason(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    val = payload.get("fallback_reason")
    return str(val or "")


def run_dependency_fallback_checks(profile: str, wait_health_seconds: float) -> None:
    running = compose_running_services(profile)
    print(f"[info] running services: {sorted(running)}")
    for service, expected_fragment in DEPENDENCY_FALLBACK_MATRIX:
        if service not in running:
            print(f"[skip] {service} not running in profile={profile}")
            continue

        print(f"[check] fault {service} -> expect fallback contains '{expected_fragment}'")
        compose_stop(profile, service)
        time.sleep(4)
        status, body = evaluate_any_status()
        if status != 200:
            raise RuntimeError(f"{service}: evaluate expected 200 under degrade path, got {status} body={body[:240]}")
        fallback_reason = _extract_fallback_reason(body)
        if expected_fragment not in fallback_reason:
            raise RuntimeError(f"{service}: fallback_reason missing '{expected_fragment}'. got={fallback_reason!r} body={body[:240]}")
        print(f"[ok] {service} fallback_reason={fallback_reason!r}")

        compose_start(profile, service)
        time.sleep(4)
        wait_decision_health_ok(deadline_seconds=min(wait_health_seconds, 300.0))
        smoke_evaluate_ok()


def main() -> int:
    p = argparse.ArgumentParser(description="Chaos smoke: stop a dependency, probe health + evaluate, recover.")
    p.add_argument("--skip-up", action="store_true", help="Assume compose already up; skip compose down at end")
    p.add_argument(
        "--fault",
        choices=("redis", "postgres"),
        default="redis",
        help="Service to stop for the fault window (default: redis)",
    )
    p.add_argument("--profile", default="core", help="Compose profile (default: core)")
    p.add_argument(
        "--dependency-fallback-checks",
        action="store_true",
        help="Run per-service fault checks (graph/feature/ml/counter/location/calibration) when services are available.",
    )
    p.add_argument(
        "--wait-health-seconds",
        type=float,
        default=900.0,
        help="Max seconds waiting for decision-api health after up",
    )
    args = p.parse_args()

    if not COMPOSE_FILE.is_file():
        print(f"Missing compose file: {COMPOSE_FILE}", file=sys.stderr)
        return 1

    profile = args.profile
    fault_svc = args.fault
    did_up = False

    try:
        if not args.skip_up:
            print(f"docker compose up -d --build (profile {profile})...")
            compose_up(profile)
            did_up = True

        print("Waiting for decision-api health...")
        wait_decision_health_ok(deadline_seconds=args.wait_health_seconds)

        print("Baseline: POST /v1/decisions/evaluate (expect 200)...")
        smoke_evaluate_ok()

        print(f"Fault: docker compose stop {fault_svc}")
        compose_stop(profile, fault_svc)
        time.sleep(4)

        print("Under fault: GET /v1/health ...")
        h_st, h_body = probe_json_health(DECISION_HEALTH)
        print(f"[info] health HTTP {h_st} body_prefix={h_body[:200]!r}")

        print("Under fault: POST /v1/decisions/evaluate (observational)...")
        ev_st, ev_raw = evaluate_any_status()
        print(f"[info] evaluate HTTP {ev_st} body_prefix={ev_raw[:200]!r}")

        print(f"Recovery: docker compose start {fault_svc}")
        compose_start(profile, fault_svc)
        time.sleep(6)
        print("Waiting for decision-api health after recovery...")
        wait_decision_health_ok(deadline_seconds=300.0)

        print("Recovery check: POST /v1/decisions/evaluate (expect 200)...")
        smoke_evaluate_ok()

        if args.dependency_fallback_checks:
            print("Running dependency fallback matrix checks...")
            run_dependency_fallback_checks(profile, args.wait_health_seconds)

        print("Chaos smoke passed (baseline + recovery).")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"compose command failed: {e}", file=sys.stderr)
        compose_logs_tail(profile)
        return 1
    except (TimeoutError, RuntimeError, OSError) as e:
        print(f"chaos smoke failed: {e}", file=sys.stderr)
        compose_logs_tail(profile)
        return 1
    finally:
        if did_up and not args.skip_up:
            print(f"docker compose down -v (profile {profile})...")
            compose_down(profile)


if __name__ == "__main__":
    sys.exit(main())
