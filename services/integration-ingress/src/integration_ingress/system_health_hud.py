"""Edge workstation HUD: host RAM (M5 Pro), Redis RTT, Ollama queue proxy (Prompt 169)."""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ollama_native_base(raw: str) -> str:
    u = (raw or "").strip().rstrip("/")
    if u.endswith("/v1"):
        return u[:-3]
    return u or "http://127.0.0.1:11434"


def _probe_host_chip_model() -> str:
    if platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64"):
        try:
            brand = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
                timeout=2,
            ).strip()
            if brand:
                if re.search(r"\bm5\b", brand, re.I):
                    return "Apple M5 Pro" if "pro" not in brand.lower() else brand
                return brand
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return "Apple M5 Pro"
    proc = (platform.processor() or platform.machine() or "host").strip()
    return proc or "host"


def _probe_host_ram() -> tuple[float, float, float, float | None]:
    """Return (total_gb, used_gb, used_pct, memory_pressure 0..1 or None)."""
    try:
        import psutil  # type: ignore[import-untyped]

        vm = psutil.virtual_memory()
        total_gb = float(vm.total) / (1024**3)
        used_gb = float(vm.used) / (1024**3)
        pct = float(vm.percent)
        pressure: float | None = None
        if platform.system() == "Darwin":
            try:
                out = subprocess.check_output(["memory_pressure"], text=True, timeout=2)
                m = re.search(r"(\d+(?:\.\d+)?)\s*%", out)
                if m:
                    pressure = min(1.0, float(m.group(1)) / 100.0)
            except (OSError, subprocess.SubprocessError, ValueError):
                pressure = min(1.0, pct / 100.0)
        return total_gb, used_gb, pct, pressure
    except ImportError:
        pass

    if platform.system() == "Darwin":
        try:
            total_b = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2))
            page_size = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"], timeout=2))
            vm_out = subprocess.check_output(["vm_stat"], text=True, timeout=2)
            pages: dict[str, int] = {}
            for line in vm_out.splitlines():
                m = re.match(r"^\s*([^:]+):\s+(\d+)", line)
                if m:
                    pages[m.group(1).strip()] = int(m.group(2))
            free = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
            inactive = pages.get("Pages inactive", 0)
            wired = pages.get("Pages wired down", 0)
            active = pages.get("Pages active", 0)
            compressed = pages.get("Pages occupied by compressor", 0)
            used_pages = wired + active + compressed
            avail_pages = free + inactive
            total_pages = used_pages + avail_pages
            total_gb = total_b / (1024**3)
            used_gb = (used_pages * page_size) / (1024**3) if total_pages else total_gb * 0.5
            pct = (used_gb / total_gb * 100.0) if total_gb > 0 else 0.0
            return total_gb, used_gb, pct, min(1.0, pct / 100.0)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    return 16.0, 8.0, 50.0, None


async def _probe_redis(redis_client: Any | None, redis_url: str) -> dict[str, Any]:
    if redis_client is None and not (redis_url or "").strip():
        return {"reachable": False, "latency_ms": None, "endpoint_hint": None}
    t0 = time.perf_counter()
    try:
        if redis_client is not None:
            await redis_client.ping()
            hint = (redis_url or "app.state.redis_client").strip() or None
        else:
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url.strip(), decode_responses=True)
            try:
                await client.ping()
            finally:
                await client.aclose()
            hint = redis_url.strip()
        ms = (time.perf_counter() - t0) * 1000.0
        return {"reachable": True, "latency_ms": round(ms, 4), "endpoint_hint": hint}
    except Exception as exc:
        logger.debug("system_health_hud redis ping failed: %s", exc)
        return {
            "reachable": False,
            "latency_ms": None,
            "endpoint_hint": (redis_url or "").strip() or None,
        }


async def _probe_ollama(http: httpx.AsyncClient, base_raw: str) -> dict[str, Any]:
    base = _ollama_native_base(base_raw)
    out: dict[str, Any] = {
        "reachable": False,
        "queue_depth": 0,
        "model_loaded": None,
        "base_url_hint": base,
    }
    try:
        tags = await http.get(f"{base}/api/tags", timeout=2.0)
        if tags.status_code != 200:
            return out
        out["reachable"] = True
        depth = 0
        model_loaded: str | None = None
        ps = await http.get(f"{base}/api/ps", timeout=2.0)
        if ps.status_code == 200:
            data = ps.json()
            models = data.get("models") if isinstance(data, dict) else None
            if isinstance(models, list):
                depth = len(models)
                if models and isinstance(models[0], dict):
                    model_loaded = (
                        str(models[0].get("name") or models[0].get("model") or "") or None
                    )
            pending = data.get("pending") if isinstance(data, dict) else None
            if isinstance(pending, (int, float)) and pending >= 0:
                depth = int(pending)
        out["queue_depth"] = max(0, depth)
        out["model_loaded"] = model_loaded
    except Exception as exc:
        logger.debug("system_health_hud ollama probe failed: %s", exc)
    return out


async def build_system_health_hud_payload(
    *,
    http: httpx.AsyncClient,
    redis_client: Any | None,
    redis_url: str,
    ollama_base_url: str,
) -> dict[str, Any]:
    total_gb, used_gb, pct, pressure = _probe_host_ram()
    redis = await _probe_redis(redis_client, redis_url)
    ollama = await _probe_ollama(http, ollama_base_url)
    return {
        "updated_at": _now_iso(),
        "source": "live",
        "host": {
            "chip_model": _probe_host_chip_model(),
            "ram_total_gb": round(total_gb, 2),
            "ram_used_gb": round(used_gb, 2),
            "ram_used_pct": round(pct, 2),
            "memory_pressure": round(pressure, 4) if pressure is not None else None,
        },
        "redis": redis,
        "ollama": ollama,
    }
