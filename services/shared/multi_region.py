"""Multi-region deployment and disaster recovery patterns.

Features:
- Region-aware routing and failover
- Health-based traffic shifting
- DR mode activation
- Cross-region replication status tracking
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RegionStatus(Enum):
    """Status of a region."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"  # Not accepting new traffic
    MAINTENANCE = "maintenance"


class FailoverMode(Enum):
    """Failover mode for multi-region deployments."""

    AUTOMATIC = "automatic"  # Automatic failover based on health
    MANUAL = "manual"  # Manual operator approval required
    MAINTENANCE = "maintenance"  # Force traffic to primary only


@dataclass
class RegionInfo:
    """Information about a deployment region."""

    region_id: str
    name: str
    status: RegionStatus
    priority: int  # Lower = higher priority for traffic
    endpoints: dict[str, str]  # service -> endpoint URL
    health_score: float  # 0-100
    last_heartbeat: float
    is_primary: bool = False


@dataclass
class FailoverConfig:
    """Configuration for multi-region failover."""

    mode: FailoverMode
    primary_region: str
    secondary_regions: list[str]
    health_threshold: float = 50.0  # Below this, consider unhealthy
    failover_delay_seconds: int = 30  # Delay before triggering failover
    auto_failback: bool = True  # Return to primary when healthy


@dataclass
class ReplicationStatus:
    """Status of cross-region replication."""

    source_region: str
    target_region: str
    lag_seconds: float
    replication_lag_records: int
    last_sync: float
    is_sync: bool


class MultiRegionManager:
    """Manages multi-region deployment and failover."""

    def __init__(self) -> None:
        self._regions: dict[str, RegionInfo] = {}
        self._config: FailoverConfig | None = None
        self._current_region: str | None = None
        self._replication_status: dict[str, ReplicationStatus] = {}
        self._health_checkers: dict[str, Callable[[], Awaitable[tuple[bool, float]]]] = {}
        self._dr_mode: bool = False
        self._dr_mode_activated_at: float | None = None

    def configure(
        self,
        config: FailoverConfig,
        current_region: str,
        regions: dict[str, RegionInfo],
    ) -> None:
        """Configure multi-region deployment."""
        self._config = config
        self._current_region = current_region
        self._regions = regions

    def register_health_checker(
        self, region_id: str, checker: Callable[[], Awaitable[tuple[bool, float]]]
    ) -> None:
        """Register a health checker for a region."""
        self._health_checkers[region_id] = checker

    async def run_health_checks(self) -> dict[str, dict[str, Any]]:
        """Run health checks for all regions."""
        results: dict[str, dict[str, Any]] = {}

        for region_id, checker in self._health_checkers.items():
            try:
                is_healthy, score = await asyncio.wait_for(checker(), timeout=10.0)
                results[region_id] = {
                    "healthy": is_healthy,
                    "score": score,
                    "status": RegionStatus.HEALTHY if is_healthy else RegionStatus.UNHEALTHY,
                }

                # Update region info
                if region_id in self._regions:
                    region = self._regions[region_id]
                    region.health_score = score
                    region.status = results[region_id]["status"]
                    region.last_heartbeat = time.time()
            except TimeoutError:
                results[region_id] = {
                    "healthy": False,
                    "score": 0.0,
                    "status": RegionStatus.UNHEALTHY,
                    "error": "Health check timed out",
                }
            except Exception as e:
                results[region_id] = {
                    "healthy": False,
                    "score": 0.0,
                    "status": RegionStatus.UNHEALTHY,
                    "error": str(e),
                }

        return results

    def get_traffic_target(self) -> str | None:
        """Determine which region should receive traffic.

        Returns the highest priority healthy region.
        """
        if not self._config:
            return self._current_region

        # If DR mode is active, return primary only if healthy
        if self._dr_mode:
            primary = self._regions.get(self._config.primary_region)
            if primary and primary.status == RegionStatus.HEALTHY:
                return self._config.primary_region
            # Fall through to find any healthy secondary

        # Sort regions by priority and health
        candidates = [
            r
            for r in self._regions.values()
            if r.status in (RegionStatus.HEALTHY, RegionStatus.DEGRADED)
        ]

        if not candidates:
            return None

        # Sort by priority (lower = higher), then by health score
        candidates.sort(key=lambda r: (r.priority, -r.health_score))
        return candidates[0].region_id

    def should_failover(self, health_results: dict[str, dict[str, Any]]) -> tuple[bool, str]:
        """Determine if failover should occur based on health results."""
        if not self._config:
            return False, "No failover configured"

        if self._config.mode == FailoverMode.MANUAL:
            return False, "Manual failover mode - operator action required"

        if self._config.mode == FailoverMode.MAINTENANCE:
            return False, "Maintenance mode - traffic pinned to primary"

        # Check primary region health
        primary = health_results.get(self._config.primary_region)
        if not primary:
            return True, "Primary region health unknown"

        if not primary["healthy"] or primary["score"] < self._config.health_threshold:
            return True, f"Primary region unhealthy (score: {primary['score']})"

        return False, "Primary region healthy"

    async def activate_dr_mode(self, reason: str) -> dict[str, Any]:
        """Activate disaster recovery mode.

        In DR mode:
        - Traffic is routed to secondary regions only
        - Write operations may be restricted
        - Replication lag monitoring is critical
        """
        self._dr_mode = True
        self._dr_mode_activated_at = time.time()

        return {
            "dr_mode": True,
            "activated_at": self._dr_mode_activated_at,
            "reason": reason,
            "primary_region": self._config.primary_region if self._config else None,
            "available_regions": [
                r.region_id for r in self._regions.values() if r.status == RegionStatus.HEALTHY
            ],
        }

    async def deactivate_dr_mode(self) -> dict[str, Any]:
        """Deactivate DR mode and return to normal operation."""
        if not self._config:
            return {"error": "Not configured"}

        # Verify primary is healthy before failback
        primary = self._regions.get(self._config.primary_region)
        if not primary or primary.status != RegionStatus.HEALTHY:
            return {
                "error": "Cannot deactivate DR mode - primary region not healthy",
                "primary_status": primary.status.value if primary else "unknown",
            }

        self._dr_mode = False
        self._dr_mode_activated_at = None

        return {
            "dr_mode": False,
            "deactivated_at": time.time(),
            "primary_region": self._config.primary_region,
        }

    def get_status(self) -> dict[str, Any]:
        """Get current multi-region status."""
        if not self._config:
            return {"configured": False}

        return {
            "configured": True,
            "current_region": self._current_region,
            "dr_mode": self._dr_mode,
            "dr_mode_activated_at": self._dr_mode_activated_at,
            "config": {
                "mode": self._config.mode.value,
                "primary_region": self._config.primary_region,
                "secondary_regions": self._config.secondary_regions,
                "health_threshold": self._config.health_threshold,
                "auto_failback": self._config.auto_failback,
            },
            "regions": {
                r.region_id: {
                    "name": r.name,
                    "status": r.status.value,
                    "priority": r.priority,
                    "health_score": r.health_score,
                    "is_primary": r.is_primary,
                    "last_heartbeat": r.last_heartbeat,
                }
                for r in self._regions.values()
            },
            "traffic_target": self.get_traffic_target(),
            "replication": {
                key: {
                    "source": status.source_region,
                    "target": status.target_region,
                    "lag_seconds": status.lag_seconds,
                    "is_sync": status.is_sync,
                }
                for key, status in self._replication_status.items()
            },
        }

    def update_replication_status(
        self, source: str, target: str, lag_seconds: float, lag_records: int
    ) -> None:
        """Update replication status for a region pair."""
        key = f"{source}->{target}"
        self._replication_status[key] = ReplicationStatus(
            source_region=source,
            target_region=target,
            lag_seconds=lag_seconds,
            replication_lag_records=lag_records,
            last_sync=time.time(),
            is_sync=lag_seconds < 5.0,  # Within 5 seconds is considered sync
        )


class RegionRouter:
    """Routes requests to appropriate region based on health and policy."""

    def __init__(self, manager: MultiRegionManager) -> None:
        self._manager = manager
        self._region_clients: dict[str, Any] = {}

    def register_client(self, region_id: str, client: Any) -> None:
        """Register a client for a region."""
        self._region_clients[region_id] = client

    async def execute(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        """Execute an operation on the best available region.

        This will:
        1. Determine the target region based on health
        2. Execute the operation
        3. Fail over to next region if it fails
        """
        target = self._manager.get_traffic_target()
        if not target:
            raise RuntimeError("No healthy regions available")

        # Get priority-ordered list of regions
        config = self._manager._config
        if config:
            regions_to_try = [config.primary_region] + config.secondary_regions
        else:
            regions_to_try = list(self._region_clients.keys())

        last_error = None
        for region_id in regions_to_try:
            client = self._region_clients.get(region_id)
            if not client:
                continue

            try:
                # Attempt operation
                method = getattr(client, operation)
                return await method(*args, **kwargs)
            except Exception as e:
                last_error = e
                # Mark region as degraded and try next
                if region_id in self._manager._regions:
                    self._manager._regions[region_id].status = RegionStatus.DEGRADED
                continue

        raise RuntimeError(f"Operation failed in all regions: {last_error}")


# Global instance
multi_region = MultiRegionManager()


def init_from_env() -> None:
    """Initialize multi-region configuration from environment variables."""
    mode_str = os.environ.get("MULTI_REGION_MODE", "disabled")
    if mode_str == "disabled":
        return

    primary = os.environ.get("PRIMARY_REGION", "us-east-1")
    secondaries = os.environ.get("SECONDARY_REGIONS", "").split(",")
    secondaries = [s.strip() for s in secondaries if s.strip()]

    mode = (
        FailoverMode(mode_str)
        if mode_str in [m.value for m in FailoverMode]
        else FailoverMode.AUTOMATIC
    )

    config = FailoverConfig(
        mode=mode,
        primary_region=primary,
        secondary_regions=secondaries,
        health_threshold=float(os.environ.get("REGION_HEALTH_THRESHOLD", "50")),
        failover_delay_seconds=int(os.environ.get("FAILOVER_DELAY_SECONDS", "30")),
        auto_failback=os.environ.get("AUTO_FAILBACK", "true").lower() == "true",
    )

    current = os.environ.get("CURRENT_REGION", primary)

    regions: dict[str, RegionInfo] = {}
    all_regions = [primary] + secondaries
    for i, region_id in enumerate(all_regions):
        regions[region_id] = RegionInfo(
            region_id=region_id,
            name=region_id,
            status=RegionStatus.HEALTHY,
            priority=i,
            endpoints={},
            health_score=100.0,
            last_heartbeat=time.time(),
            is_primary=(region_id == primary),
        )

    multi_region.configure(config, current, regions)
