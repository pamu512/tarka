"""LLM provider health monitoring with automatic failover and cost tracking.

Features:
- Health checks for each configured provider
- Automatic failover to healthy providers
- Cost tracking per provider and model
- Latency monitoring
- Circuit breaker pattern for failing providers
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx


@dataclass
class ProviderHealth:
    """Health status for an LLM provider."""

    provider: str
    is_healthy: bool
    last_check: float
    latency_ms: float
    error_count: int
    success_count: int
    consecutive_failures: int
    circuit_open: bool
    last_error: str | None = None

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.error_count
        if total == 0:
            return 1.0  # Assume healthy if no data
        return self.success_count / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "is_healthy": self.is_healthy,
            "last_check": self.last_check,
            "latency_ms": round(self.latency_ms, 2),
            "success_rate": round(self.success_rate, 3),
            "consecutive_failures": self.consecutive_failures,
            "circuit_open": self.circuit_open,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "last_error": self.last_error,
        }


@dataclass
class CostRecord:
    """Cost tracking for LLM calls."""

    provider: str
    model: str
    timestamp: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    is_error: bool = False


@dataclass
class ProviderCostSummary:
    """Aggregated cost data for a provider."""

    provider: str
    total_calls: int
    error_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    models: dict[str, dict[str, Any]] = field(default_factory=dict)


class LLMHealthMonitor:
    """Monitor health of LLM providers with circuit breaker pattern."""

    # Circuit breaker settings
    CIRCUIT_FAILURE_THRESHOLD = 5
    CIRCUIT_RECOVERY_SECONDS = 60

    # Health check settings
    CHECK_INTERVAL_SECONDS = 30
    HEALTHY_LATENCY_THRESHOLD_MS = 5000
    MAX_LATENCY_THRESHOLD_MS = 30000

    def __init__(self) -> None:
        self._health: dict[str, ProviderHealth] = {}
        self._costs: list[CostRecord] = []
        self._circuit_open_until: dict[str, float] = {}
        self._last_check: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _get_provider_key(self, provider: str, model: str) -> str:
        return f"{provider}:{model}"

    async def check_provider_health(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        http: httpx.AsyncClient,
    ) -> ProviderHealth:
        """Check health of a specific provider."""
        key = self._get_provider_key(provider, model)
        now = time.time()

        # Check if circuit is open
        if provider in self._circuit_open_until:
            if now < self._circuit_open_until[provider]:
                health = ProviderHealth(
                    provider=provider,
                    is_healthy=False,
                    last_check=now,
                    latency_ms=0,
                    error_count=0,
                    success_count=0,
                    consecutive_failures=0,
                    circuit_open=True,
                    last_error="Circuit breaker open",
                )
                self._health[key] = health
                return health
            else:
                # Circuit half-open, try again
                del self._circuit_open_until[provider]

        # Perform health check
        start = time.time()
        is_healthy = False
        latency_ms = 0.0
        error_msg = None

        try:
            if provider in ("openai", "ollama"):
                # OpenAI-compatible health check
                headers = {"Authorization": f"Bearer {api_key}"}
                # Use models endpoint as lightweight check
                r = await http.get(
                    f"{base_url}/models",
                    headers=headers,
                    timeout=10.0,
                )
                is_healthy = r.status_code == 200

            elif provider == "anthropic":
                # Anthropic health check
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                }
                r = await http.get(
                    f"{base_url}/models",
                    headers=headers,
                    timeout=10.0,
                )
                is_healthy = r.status_code == 200

            elif provider == "gemini":
                # Gemini lightweight check
                r = await http.get(
                    f"{base_url}/models?key={api_key}",
                    timeout=10.0,
                )
                is_healthy = r.status_code == 200

            latency_ms = (time.time() - start) * 1000

        except Exception as e:
            error_msg = str(e)
            is_healthy = False

        async with self._lock:
            existing = self._health.get(key)
            if existing:
                consecutive_failures = existing.consecutive_failures + 1 if not is_healthy else 0
                error_count = existing.error_count + (0 if is_healthy else 1)
                success_count = existing.success_count + (1 if is_healthy else 0)
            else:
                consecutive_failures = 0 if is_healthy else 1
                error_count = 0 if is_healthy else 1
                success_count = 1 if is_healthy else 0

            # Check if we should open circuit
            if consecutive_failures >= self.CIRCUIT_FAILURE_THRESHOLD:
                self._circuit_open_until[provider] = now + self.CIRCUIT_RECOVERY_SECONDS

            health = ProviderHealth(
                provider=provider,
                is_healthy=is_healthy,
                last_check=now,
                latency_ms=latency_ms,
                error_count=error_count,
                success_count=success_count,
                consecutive_failures=consecutive_failures,
                circuit_open=provider in self._circuit_open_until,
                last_error=error_msg,
            )
            self._health[key] = health

        return health

    async def get_healthy_providers(
        self, providers: list[tuple[str, str, str, str]], http: httpx.AsyncClient
    ) -> list[str]:
        """Get list of healthy providers, checking if needed."""
        healthy: list[str] = []

        for provider, base_url, api_key, model in providers:
            key = self._get_provider_key(provider, model)

            # Check if we need to refresh health status
            last_check = self._last_check.get(key, 0)
            if time.time() - last_check > self.CHECK_INTERVAL_SECONDS:
                await self.check_provider_health(provider, base_url, api_key, model, http)
                self._last_check[key] = time.time()

            health = self._health.get(key)
            if health and health.is_healthy and not health.circuit_open:
                healthy.append(provider)

        return healthy

    async def select_best_provider(
        self,
        preferred: list[str],
        providers_config: dict[str, tuple[str, str, str]],  # provider -> (base_url, api_key, model)
        http: httpx.AsyncClient,
    ) -> str | None:
        """Select the best healthy provider from preferred list."""
        check_tasks = []
        for provider in preferred:
            if provider in providers_config:
                base_url, api_key, model = providers_config[provider]
                check_tasks.append(
                    self.check_provider_health(provider, base_url, api_key, model, http)
                )

        if not check_tasks:
            return None

        # Check all in parallel
        results = await asyncio.gather(*check_tasks, return_exceptions=True)

        # Find first healthy provider (by order of preference)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue
            if result.is_healthy and not result.circuit_open:
                return preferred[i]

        # No healthy providers - return first preferred anyway (fail open)
        return preferred[0] if preferred else None

    def record_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        is_error: bool = False,
    ) -> None:
        """Record cost for an LLM call."""
        # Approximate pricing (adjust as needed)
        pricing = {
            "gpt-4o": {"input": 0.005, "output": 0.015},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "claude-3-5-sonnet-latest": {"input": 0.003, "output": 0.015},
            "gemini-2.0-flash": {"input": 0.00035, "output": 0.00105},
            "llama3.1:8b": {"input": 0.0, "output": 0.0},  # Local = free
        }

        model_pricing = pricing.get(model, {"input": 0.001, "output": 0.002})
        input_cost = (input_tokens / 1000) * model_pricing["input"]
        output_cost = (output_tokens / 1000) * model_pricing["output"]
        total_cost = input_cost + output_cost

        record = CostRecord(
            provider=provider,
            model=model,
            timestamp=time.time(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=total_cost,
            latency_ms=latency_ms,
            is_error=is_error,
        )
        self._costs.append(record)

        # Trim old records (keep last 10k)
        if len(self._costs) > 10000:
            self._costs = self._costs[-5000:]

    def get_cost_summary(self, hours: int = 24, provider: str | None = None) -> dict[str, Any]:
        """Get cost summary for the specified period."""
        cutoff = time.time() - (hours * 3600)
        filtered = [c for c in self._costs if c.timestamp >= cutoff]

        if provider:
            filtered = [c for c in filtered if c.provider == provider]

        if not filtered:
            return {
                "period_hours": hours,
                "total_calls": 0,
                "total_cost_usd": 0.0,
                "by_provider": {},
            }

        # Aggregate by provider
        by_provider: dict[str, ProviderCostSummary] = {}
        for record in filtered:
            if record.provider not in by_provider:
                by_provider[record.provider] = ProviderCostSummary(
                    provider=record.provider,
                    total_calls=0,
                    error_calls=0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    avg_latency_ms=0.0,
                    models={},
                )

            summary = by_provider[record.provider]
            summary.total_calls += 1
            if record.is_error:
                summary.error_calls += 1
            summary.total_input_tokens += record.input_tokens
            summary.total_output_tokens += record.output_tokens
            summary.total_cost_usd += record.estimated_cost_usd

            if record.model not in summary.models:
                summary.models[record.model] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            model_stats = summary.models[record.model]
            model_stats["calls"] += 1
            model_stats["input_tokens"] += record.input_tokens
            model_stats["output_tokens"] += record.output_tokens
            model_stats["cost_usd"] += record.estimated_cost_usd

        # Calculate averages
        total_latency = sum(c.latency_ms for c in filtered)
        avg_latency = total_latency / len(filtered) if filtered else 0

        for summary in by_provider.values():
            provider_records = [c for c in filtered if c.provider == summary.provider]
            summary.avg_latency_ms = (
                sum(c.latency_ms for c in provider_records) / len(provider_records)
                if provider_records
                else 0
            )

        return {
            "period_hours": hours,
            "total_calls": len(filtered),
            "total_input_tokens": sum(c.input_tokens for c in filtered),
            "total_output_tokens": sum(c.output_tokens for c in filtered),
            "total_cost_usd": round(sum(c.estimated_cost_usd for c in filtered), 4),
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate": round(sum(1 for c in filtered if c.is_error) / len(filtered), 4)
            if filtered
            else 0,
            "by_provider": {
                k: {
                    "total_calls": v.total_calls,
                    "error_calls": v.error_calls,
                    "error_rate": round(v.error_calls / v.total_calls, 4) if v.total_calls else 0,
                    "input_tokens": v.total_input_tokens,
                    "output_tokens": v.total_output_tokens,
                    "cost_usd": round(v.total_cost_usd, 4),
                    "avg_latency_ms": round(v.avg_latency_ms, 2),
                    "models": v.models,
                }
                for k, v in by_provider.items()
            },
        }

    def get_health_status(self) -> dict[str, Any]:
        """Get current health status of all monitored providers."""
        return {
            "providers": {k: v.to_dict() for k, v in self._health.items()},
            "circuits_open": list(self._circuit_open_until.keys()),
        }


# Global instance
llm_health = LLMHealthMonitor()
