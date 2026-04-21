#!/usr/bin/env python3
"""
Bring up deploy/docker-compose.yml with --profile full, wait for HTTP health, POST evaluate, tear down.

Used by GitHub Actions; runnable locally from repo root:
  python scripts/ci/full_stack_smoke.py
  python scripts/ci/full_stack_smoke.py --skip-up   # stack already running (no compose down)
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

JSON_HEALTH = [
    ("decision-api", "http://127.0.0.1:8000/v1/health"),
    ("graph-service", "http://127.0.0.1:8001/v1/health"),
    ("case-api", "http://127.0.0.1:8002/v1/health"),
    ("integration-ingress", "http://127.0.0.1:8003/v1/health"),
    ("feature-service", "http://127.0.0.1:8004/v1/health"),
    ("ml-scoring", "http://127.0.0.1:8005/v1/health"),
    ("investigation-agent", "http://127.0.0.1:8006/v1/health"),
    ("event-ingest", "http://127.0.0.1:8007/v1/health"),
    ("analytics-sink", "http://127.0.0.1:8008/v1/health"),
    ("graphql-gateway", "http://127.0.0.1:8010/v1/health"),
]

HTTP200_ONLY = [
    ("frontend", "http://127.0.0.1:3000/"),
    ("opa", "http://127.0.0.1:8181/health"),
]


def _compose_cmd() -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "--profile",
        "full",
    ]


def compose_up() -> None:
    subprocess.run(
        _compose_cmd() + ["up", "-d", "--build"],
        cwd=REPO_ROOT,
        check=True,
    )


def compose_down() -> None:
    subprocess.run(
        _compose_cmd() + ["down", "-v", "--remove-orphans"],
        cwd=REPO_ROOT,
        check=False,
    )


def compose_logs_tail() -> None:
    subprocess.run(
        _compose_cmd() + ["logs", "--tail", "80"],
        cwd=REPO_ROOT,
        check=False,
    )


def probe_json_ok(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode())
            return body.get("status") == "ok"
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return False


def probe_http_200(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def wait_for_stack(deadline_seconds: float = 1200.0, poll: float = 5.0) -> None:
    pending_json = {name: url for name, url in JSON_HEALTH}
    pending_200 = {name: url for name, url in HTTP200_ONLY}
    deadline = time.monotonic() + deadline_seconds

    while (pending_json or pending_200) and time.monotonic() < deadline:
        for name, url in list(pending_json.items()):
            if probe_json_ok(url):
                print(f"[ok] {name} {url}")
                del pending_json[name]
        for name, url in list(pending_200.items()):
            if probe_http_200(url):
                print(f"[ok] {name} {url}")
                del pending_200[name]
        if pending_json or pending_200:
            rem = sorted(pending_json) + sorted(pending_200)
            print(f"[wait] remaining: {rem} ({int(deadline - time.monotonic())}s left)")
            time.sleep(poll)

    if pending_json or pending_200:
        print("TIMEOUT waiting for:", sorted(pending_json) + sorted(pending_200), file=sys.stderr)
        raise TimeoutError("stack health checks")


def smoke_evaluate() -> None:
    payload = json.dumps(
        {
            "tenant_id": "ci_stack",
            "event_type": "login",
            "entity_id": "ci-smoke-entity",
            "payload": {"source": "full_stack_smoke"},
        }
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/v1/decisions/evaluate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            if resp.status != 200:
                raise RuntimeError(f"evaluate returned {resp.status}: {raw[:1200]}")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"evaluate returned non-JSON ({e}): {raw[:1200]}") from e
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"evaluate HTTP {e.code}: {detail[:1200]}") from e
    _assert_evaluate_contract_shape(body)
    print(f"[ok] POST /v1/decisions/evaluate trace_id={body.get('trace_id')}")


def _assert_evaluate_contract_shape(body: dict[str, object]) -> None:
    required_top_level = {
        "trace_id",
        "decision",
        "score",
        "tags",
        "rule_hits",
        "reasons",
        "inference_context",
    }
    missing = sorted(k for k in required_top_level if k not in body)
    if missing:
        raise RuntimeError(f"evaluate missing required keys: {missing}; got={sorted(body.keys())}")

    if body.get("decision") not in {"allow", "review", "deny"}:
        raise RuntimeError(f"unexpected decision value: {body.get('decision')!r}")
    if not isinstance(body.get("score"), (int, float)):
        raise RuntimeError("evaluate.score must be numeric")
    for key in ("tags", "rule_hits", "reasons"):
        if not isinstance(body.get(key), list):
            raise RuntimeError(f"evaluate.{key} must be a list")
    inf = body.get("inference_context")
    if not isinstance(inf, dict):
        raise RuntimeError("evaluate.inference_context must be an object")

    required_inference = {
        "schema_version",
        "driver_reasons",
        "driver_explain",
        "top_signals",
        "graph_risk_score",
        "external_signal_score",
        "policy_experiment_id",
    }
    missing_inference = sorted(k for k in required_inference if k not in inf)
    if missing_inference:
        raise RuntimeError(f"inference_context missing keys: {missing_inference}")


def main() -> int:
    p = argparse.ArgumentParser(description="Full Docker Compose stack smoke (CI).")
    p.add_argument("--skip-up", action="store_true", help="Assume compose is already up; skip compose down")
    p.add_argument("--down-only", action="store_true", help="Only run docker compose down -v")
    p.add_argument(
        "--wait-seconds",
        type=float,
        default=1200.0,
        help="Max seconds to wait for all health checks (default 20m)",
    )
    args = p.parse_args()

    if not COMPOSE_FILE.is_file():
        print(f"Missing compose file: {COMPOSE_FILE}", file=sys.stderr)
        return 1

    if args.down_only:
        compose_down()
        return 0

    did_up = False
    try:
        if not args.skip_up:
            print("docker compose up -d --build (profile full)...")
            compose_up()
            did_up = True
        print("Waiting for health endpoints...")
        wait_for_stack(deadline_seconds=args.wait_seconds)
        print("Smoke: synchronous evaluate...")
        smoke_evaluate()
        print("Full stack smoke passed.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"compose command failed: {e}", file=sys.stderr)
        compose_logs_tail()
        return 1
    except (TimeoutError, RuntimeError, urllib.error.HTTPError, OSError) as e:
        print(f"smoke failed: {e}", file=sys.stderr)
        compose_logs_tail()
        return 1
    finally:
        if did_up:
            print("docker compose down -v ...")
            compose_down()


if __name__ == "__main__":
    sys.exit(main())
