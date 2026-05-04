"""Standardized health check endpoints for Kubernetes and ops monitoring.

Provides:
- /v1/health - Liveness probe (is the process running)
- /v1/ready - Readiness probe (is the service ready to accept traffic)
- /v1/slo - Service level objectives and metrics
- /v1/health/deep - Deep health check with dependency validation
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from observability import get_metrics

router = APIRouter(prefix="/v1", tags=["health"])

# Health check registry
_health_checks: dict[str, Callable[[], Awaitable[tuple[bool, str]]]] = {}
_readiness_checks: dict[str, Callable[[], Awaitable[tuple[bool, str]]]] = {}


class HealthStatus(BaseModel):
    """Health check response model."""

    status: str
    service: str
    version: str
    uptime_seconds: float
    timestamp: float


class ReadinessStatus(BaseModel):
    """Readiness check response model."""

    ready: bool
    service: str
    checks: dict[str, dict[str, Any]]
    timestamp: float


class DeepHealthStatus(BaseModel):
    """Deep health check with dependency validation."""

    healthy: bool
    service: str
    checks: dict[str, dict[str, Any]]
    timestamp: float


class SLOStatus(BaseModel):
    """Service Level Objectives status."""

    service: str
    metrics: dict[str, Any]
    slo_targets: dict[str, float]
    current_vs_target: dict[str, dict[str, float]]
    timestamp: float


# Global state
_start_time = time.time()
_service_name = "unknown"
_service_version = "unknown"


def configure_health(service_name: str, service_version: str) -> None:
    """Configure global health check settings."""
    global _service_name, _service_version
    _service_name = service_name
    _service_version = service_version


def register_health_check(
    name: str, check: Callable[[], Awaitable[tuple[bool, str]]]
) -> None:
    """Register a liveness health check.
    
    The check function should return (is_healthy, message).
    """
    _health_checks[name] = check


def register_readiness_check(
    name: str, check: Callable[[], Awaitable[tuple[bool, str]]]
) -> None:
    """Register a readiness check.
    
    The check function should return (is_ready, message).
    """
    _readiness_checks[name] = check


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    """Liveness probe - returns 200 if process is running.
    
    Kubernetes uses this to determine if the container should be restarted.
    """
    return HealthStatus(
        status="healthy",
        service=_service_name,
        version=_service_version,
        uptime_seconds=time.time() - _start_time,
        timestamp=time.time(),
    )


@router.get("/ready", response_model=ReadinessStatus)
async def readiness_check() -> ReadinessStatus:
    """Readiness probe - returns 200 if service is ready to accept traffic.
    
    Kubernetes uses this to determine if the pod should receive traffic.
    Returns 503 if any readiness check fails.
    """
    checks: dict[str, dict[str, Any]] = {}
    all_ready = True

    for name, check in _readiness_checks.items():
        try:
            is_ready, message = await asyncio.wait_for(check(), timeout=5.0)
            checks[name] = {"ready": is_ready, "message": message}
            if not is_ready:
                all_ready = False
        except asyncio.TimeoutError:
            checks[name] = {"ready": False, "message": "Check timed out"}
            all_ready = False
        except Exception as e:
            checks[name] = {"ready": False, "message": str(e)}
            all_ready = False

    if not all_ready:
        raise HTTPException(
            status_code=503,
            detail=ReadinessStatus(
                ready=False,
                service=_service_name,
                checks=checks,
                timestamp=time.time(),
            ).model_dump(),
        )

    return ReadinessStatus(
        ready=True,
        service=_service_name,
        checks=checks,
        timestamp=time.time(),
    )


@router.get("/health/deep", response_model=DeepHealthStatus)
async def deep_health_check() -> DeepHealthStatus:
    """Deep health check with all registered health checks.
    
    This validates both liveness and dependency health.
    Returns detailed status for each check.
    """
    checks: dict[str, dict[str, Any]] = {}
    all_healthy = True

    # Run all health checks
    all_checks = {**_health_checks, **_readiness_checks}

    for name, check in all_checks.items():
        start = time.time()
        try:
            is_healthy, message = await asyncio.wait_for(check(), timeout=10.0)
            latency_ms = (time.time() - start) * 1000
            checks[name] = {
                "healthy": is_healthy,
                "message": message,
                "latency_ms": round(latency_ms, 2),
            }
            if not is_healthy:
                all_healthy = False
        except asyncio.TimeoutError:
            checks[name] = {
                "healthy": False,
                "message": "Check timed out after 10s",
                "latency_ms": 10000,
            }
            all_healthy = False
        except Exception as e:
            checks[name] = {"healthy": False, "message": str(e), "latency_ms": 0}
            all_healthy = False

    return DeepHealthStatus(
        healthy=all_healthy,
        service=_service_name,
        checks=checks,
        timestamp=time.time(),
    )


@router.get("/slo", response_model=SLOStatus)
async def slo_status() -> SLOStatus:
    """Service Level Objectives status.
    
    Returns current metrics against SLO targets.
    """
    try:
        m = get_metrics()
        summary = m.request_count_summary()

        # Get custom counters for error rates
        metrics_data = m.custom_counter_summary()

        # Calculate error rates
        total_requests = summary.get("http_requests_total_observed", 0)
        server_errors = summary.get("http_server_errors_total_observed", 0)
        client_errors = summary.get("http_client_errors_total_observed", 0)

        error_rate = (
            (server_errors + client_errors) / total_requests if total_requests > 0 else 0
        )

        # SLO targets (these should be configurable)
        slo_targets = {
            "availability": 0.999,  # 99.9%
            "error_rate": 0.001,  # 0.1%
            "p95_latency_ms": 500,  # 500ms
            "p99_latency_ms": 1000,  # 1s
        }

        # Current metrics
        current = {
            "availability": 1.0 - error_rate,
            "error_rate": error_rate,
            "p95_latency_ms": metrics_data.get("p95_latency_ms", 0),
            "p99_latency_ms": metrics_data.get("p99_latency_ms", 0),
        }

        # Compare to targets
        current_vs_target = {}
        for metric, target in slo_targets.items():
            actual = current.get(metric, 0)
            if metric in ("error_rate", "p95_latency_ms", "p99_latency_ms"):
                # Lower is better
                is_met = actual <= target
            else:
                # Higher is better
                is_met = actual >= target

            current_vs_target[metric] = {
                "target": target,
                "current": round(actual, 4),
                "is_met": is_met,
                "delta": round(actual - target, 4),
            }

        return SLOStatus(
            service=_service_name,
            metrics={
                "total_requests": total_requests,
                "server_errors": server_errors,
                "client_errors": client_errors,
                **metrics_data,
            },
            slo_targets=slo_targets,
            current_vs_target=current_vs_target,
            timestamp=time.time(),
        )
    except Exception:
        # If metrics fail, return basic info
        return SLOStatus(
            service=_service_name,
            metrics={"error": "metrics_unavailable"},
            slo_targets={},
            current_vs_target={},
            timestamp=time.time(),
        )


# Common health check implementations

async def check_redis_health(redis_client: Any) -> tuple[bool, str]:
    """Check Redis connectivity."""
    try:
        await redis_client.ping()
        return True, "Redis is responsive"
    except Exception as e:
        return False, f"Redis check failed: {e}"


async def check_postgres_health(db_session_maker: Any) -> tuple[bool, str]:
    """Check PostgreSQL connectivity."""
    try:
        async with db_session_maker() as session:
            result = await session.execute("SELECT 1")
            if result.scalar() == 1:
                return True, "PostgreSQL is responsive"
            return False, "PostgreSQL returned unexpected result"
    except Exception as e:
        return False, f"PostgreSQL check failed: {e}"


async def check_http_service_health(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Check HTTP service health."""
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{url}/v1/health", timeout=timeout)
            if r.status_code == 200:
                return True, f"Service at {url} is healthy"
            return False, f"Service at {url} returned {r.status_code}"
    except Exception as e:
        return False, f"Service at {url} check failed: {e}"


def setup_health_endpoints(app: FastAPI, service_name: str, service_version: str) -> None:
    """Setup standardized health endpoints for a service.
    
    Usage:
        from health_endpoints import setup_health_endpoints, register_readiness_check
        
        app = FastAPI()
        setup_health_endpoints(app, "decision-api", "1.2.0")
        
        # Register custom readiness checks
        register_readiness_check("database", check_db)
        register_readiness_check("redis", check_redis)
    """
    configure_health(service_name, service_version)
    app.include_router(router)
