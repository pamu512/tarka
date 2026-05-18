"""Unit tests: velocity key layout + bucket alignment."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_build_velocity_commands_counts_windows_device_and_ips() -> None:
    from orchestrator.anumana_velocity import build_velocity_incr_expire_commands, device_hash_token

    fp = "ab" * 32
    dtok = device_hash_token(fp)
    ips = ["192.0.2.1", "198.51.100.9"]
    cmds = build_velocity_incr_expire_commands(
        tenant_id="acme",
        device_token=dtok,
        ip_tokens=ips,
        now_unix=1_700_000_000,
    )
    assert len(cmds) == 9  # 3 windows * (1 device + 2 ips)
    keys = [c[0] for c in cmds]
    assert any(":device:1m:" in k and dtok in k for k in keys)
    assert any(":ip:5m:192.0.2.1:" in k for k in keys)
    assert all(c[1] > 0 for c in cmds)


def test_velocity_bucket_alignment() -> None:
    from orchestrator.anumana_velocity import velocity_bucket

    assert velocity_bucket(60, 120) == 2
    assert velocity_bucket(300, 600) == 2
    assert velocity_bucket(3600, 7200) == 2
