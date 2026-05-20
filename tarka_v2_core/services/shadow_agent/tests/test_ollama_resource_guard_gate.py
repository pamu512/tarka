"""Gate (Prompt 134): merged subprocess env for Ollama — caps live in docker-compose / host env."""

from __future__ import annotations

import subprocess
import sys
import time
from multiprocessing import Process

import pytest
from shadow_agent.ollama_resource_guard import (
    RSS_HEADROOM_LIMIT_BYTES,
    ollama_resource_environ,
    popen_ollama,
)


def test_ollama_resource_environ_merges_base_without_forcing_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_NUM_PARALLEL", raising=False)
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    env = ollama_resource_environ({"CUSTOM_GATE": "134"})
    assert env["CUSTOM_GATE"] == "134"
    assert "OLLAMA_NUM_PARALLEL" not in env
    assert "OLLAMA_MAX_LOADED_MODELS" not in env


def test_ollama_resource_environ_preserves_docker_compose_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docker-compose.local.yml (or host) sets parallelism — subprocess inherits."""
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "1")
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "1")
    env = ollama_resource_environ({"CUSTOM_GATE": "134"})
    assert env["OLLAMA_NUM_PARALLEL"] == "1"
    assert env["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert env["CUSTOM_GATE"] == "134"


def test_popen_ollama_inherits_env_via_python_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "1")
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "1")
    env = ollama_resource_environ()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os; assert os.environ['OLLAMA_NUM_PARALLEL']=='1'; "
            "assert os.environ['OLLAMA_MAX_LOADED_MODELS']=='1'; print('ok')",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, (out, err)


def _shadow_stub_worker() -> None:
    """Light stand-in for “Shadow running” (import package + short sleep)."""
    import shadow_agent  # noqa: F401 — load agent package like a sidecar worker

    time.sleep(0.35)


def _psutil_available() -> bool:
    try:
        import psutil  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _psutil_available(), reason="psutil required for RSS gate (pip install psutil)"
)
def test_peak_rss_stays_under_16gb_while_shadow_stub_running() -> None:
    import psutil

    p = Process(target=_shadow_stub_worker)
    p.start()
    try:
        proc = psutil.Process(p.pid)
        peak = 0
        deadline = time.monotonic() + 8.0
        while p.is_alive() and time.monotonic() < deadline:
            try:
                rss = proc.memory_info().rss
                for c in proc.children(recursive=True):
                    rss += c.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            peak = max(peak, rss)
            time.sleep(0.04)
        p.join(timeout=10)
        assert p.exitcode == 0
    finally:
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)

    assert peak < RSS_HEADROOM_LIMIT_BYTES, (
        f"Stub Shadow process tree RSS peak {peak / (1024**3):.3f} GiB "
        f"exceeds headroom limit {RSS_HEADROOM_LIMIT_BYTES / (1024**3):.0f} GiB"
    )


def test_popen_ollama_smoke_when_ollama_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional: if ``ollama`` exists, ``ollama --version`` inherits merged env."""
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "8")
    try:
        proc = popen_ollama(["--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        pytest.skip("ollama binary not on PATH")
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, (out, err)
