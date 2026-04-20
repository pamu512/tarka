#!/usr/bin/env python3
"""
Chaos smoke (R4.2): bring up deploy/docker-compose.yml with --profile core, baseline evaluate,
stop Redis (fault), run health + evaluate (observational), restart Redis, verify evaluate recovery, tear down.

Manual / CI:
  python3 scripts/chaos/chaos_smoke.py
  python3 scripts/chaos/chaos_smoke.py --skip-up    # stack already running (no down)
  python3 scripts/chaos/chaos_smoke.py --fault postgres   # optional; harsher than redis
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
