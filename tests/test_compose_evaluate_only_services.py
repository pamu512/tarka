"""Default lite compose is evaluate-only. Additive overlays bring planes back.

ponytail: stdlib scan of compose YAML (no docker). Fails if investigation-agent,
signal-api, or integration-ingress return to the unprofiled lite service set.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LITE = REPO / "infra" / "deploy" / "docker-compose.lite.yml"
INVESTIGATION = REPO / "infra" / "deploy" / "docker-compose.investigation.yml"
SIGNALS = REPO / "infra" / "deploy" / "docker-compose.signals.yml"

PLANE_SERVICES = ("investigation-agent", "signal-api", "integration-ingress")
EVALUATE_ONLY = ("postgres", "redis", "core-api", "frontend")


def _service_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "services:")
    except StopIteration as exc:
        raise AssertionError("compose file has no services: block") from exc
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        if line.startswith("volumes:"):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            name = line.strip().rstrip(":")
            if name and not name.startswith("#"):
                current = name
                blocks[current] = []
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(body) for name, body in blocks.items()}


def _unprofiled(blocks: dict[str, str]) -> set[str]:
    return {name for name, body in blocks.items() if "profiles:" not in body}


def test_lite_default_excludes_plane_services() -> None:
    blocks = _service_blocks(LITE.read_text(encoding="utf-8"))
    default = _unprofiled(blocks)
    for required in EVALUATE_ONLY:
        assert required in default, f"{required} must stay on evaluate-only lite"
    for plane in PLANE_SERVICES:
        assert plane not in default, f"{plane} must not start on default lite"
    assert "nats" not in default, "nats is unused for sync evaluate; keep it on ingest/signals"


def test_overlays_restore_plane_services() -> None:
    investigation = _service_blocks(INVESTIGATION.read_text(encoding="utf-8"))
    signals = _service_blocks(SIGNALS.read_text(encoding="utf-8"))
    assert "investigation-agent" in investigation
    assert "profiles:" not in investigation["investigation-agent"]
    assert "signal-api" in signals
    assert "integration-ingress" in signals
    assert "nats" in signals
    assert "profiles:" not in signals["signal-api"]
    assert "profiles:" not in signals["integration-ingress"]


if __name__ == "__main__":
    test_lite_default_excludes_plane_services()
    test_overlays_restore_plane_services()
    print("ok")
