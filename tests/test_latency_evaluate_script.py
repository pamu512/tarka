"""latency_evaluate.py: warmup status codes are printed and non-200s count as errors."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "benchmarks"
    / "latency_evaluate.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("latency_evaluate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod: ModuleType, monkeypatch, capsys, *, codes: list[int], warmup: int) -> tuple[int, str]:
    calls = iter(codes)

    def fake_one_post(url, body, timeout):
        return 1.0, next(calls)

    monkeypatch.setattr(mod, "one_post", fake_one_post)
    requests = len(codes) - warmup
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "latency_evaluate.py",
            "--url",
            "http://127.0.0.1:8000",
            "--requests",
            str(requests),
            "--concurrency",
            "2",
            "--warmup",
            str(warmup),
        ],
    )
    rc = mod.main()
    out = capsys.readouterr().out
    return rc, out


def test_warmup_status_codes_are_printed(monkeypatch, capsys):
    mod = _load_module()
    # 3 warmup calls (one 500), then 5 measured 200s.
    codes = [500, 200, 200] + [200] * 5
    rc, out = _run(mod, monkeypatch, capsys, codes=codes, warmup=3)
    assert rc == 0
    assert "warmup: requests=3 status: {500: 1, 200: 2}" in out
    assert "errors=0" in out
    assert "status: {200: 5}" in out


def test_non_200_measured_requests_increment_errors(monkeypatch, capsys):
    mod = _load_module()
    # 1 warmup 200, then 6 measured: 4x 500 + 2x 200.
    codes = [200] + [500, 500, 500, 500, 200, 200]
    rc, out = _run(mod, monkeypatch, capsys, codes=codes, warmup=1)
    assert rc == 1
    assert "errors=4" in out
    assert "500: 4" in out
    assert "200: 2" in out


def test_error_bar_is_not_raised_at_half(monkeypatch, capsys):
    mod = _load_module()
    # 6 requests, 3 errors: errors == requests // 2 must still exit 0.
    codes = [200] * 3 + [500] * 3
    rc, out = _run(mod, monkeypatch, capsys, codes=codes, warmup=0)
    assert rc == 0
    assert "errors=3" in out
    assert "warmup" not in out
