"""Challenge dispatch against a real local sink process (Track D — not httpx mock)."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.calibration_api import router as calibration_router

_REPO = Path(__file__).resolve().parents[3]
_SINK = _REPO / "scripts" / "e2e" / "challenge_webhook_sink.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live_challenge_sink(tmp_path):
    port = _free_port()
    log_file = tmp_path / "sink.jsonl"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(_SINK),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-file",
            str(log_file),
        ],
        cwd=str(_REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}/challenge"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/", timeout=0.3)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        err = proc.stderr.read() if proc.stderr else b""
        proc.kill()
        raise RuntimeError(f"sink failed to start: {err!r}")
    yield {"url": url, "log_file": log_file, "port": port}
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_challenge_dispatch_hits_live_sink(monkeypatch, live_challenge_sink):
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_URL", live_challenge_sink["url"])
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    from auth_rbac import AuthUser

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(calibration_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/calibration/challenge/dispatch",
            json={
                "tenant_id": "demo",
                "trace_id": "t-live-sink",
                "entity_id": "e1",
                "decision": "review",
                "recommended_action": "step_up_mfa",
            },
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    delivery = body.get("delivery") or {}
    assert delivery.get("ok") is True
    assert delivery.get("status_code") == 200

    await asyncio.sleep(0.05)
    log_text = live_challenge_sink["log_file"].read_text(encoding="utf-8")
    assert "t-live-sink" in log_text
    assert "step_up_mfa" in log_text
