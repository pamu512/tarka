"""Device intelligence database with behavioral biometrics and reputation scoring.

Extends fingerprint_store with:
- Behavioral biometric profiles (mouse/keystroke dynamics)
- Device reputation scoring based on fraud history
- Cross-tenant device linking for consortium detection
- Device-to-IP velocity tracking
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis

# Redis key prefixes
BIOMETRIC_PREFIX = "fraud:biometric:"
DEVICE_REP_PREFIX = "fraud:devrep:"
DEVICE_IP_VELOCITY_PREFIX = "fraud:devipvel:"
CONSORTIUM_DEVICE_PREFIX = "fraud:consortium:dev:"

BIOMETRIC_TTL = 86400 * 30  # 30 days
DEVICE_REP_TTL = 86400 * 180  # 6 months
IP_VELOCITY_TTL = 86400 * 7  # 7 days


@dataclass
class BiometricProfile:
    """Behavioral biometrics for a device entity."""

    entity_id: str
    device_id: str
    tenant_id: str

    # Typing dynamics
    avg_inter_key_ms: float
    std_inter_key_ms: float
    avg_hold_ms: float
    key_count_total: int

    # Mouse dynamics
    avg_speed_px_ms: float
    std_speed_px_ms: float
    click_count_total: int

    # Session patterns
    time_to_first_interaction_ms: float
    paste_count_per_session: float
    tab_switches_per_session: float

    # Bot indicators frequency
    zero_mouse_movement_rate: float
    constant_typing_rate: float
    no_scroll_rate: float

    # Metadata
    sample_count: int
    first_seen: float
    last_seen: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "device_id": self.device_id,
            "tenant_id": self.tenant_id,
            "typing": {
                "avg_inter_key_ms": self.avg_inter_key_ms,
                "std_inter_key_ms": self.std_inter_key_ms,
                "avg_hold_ms": self.avg_hold_ms,
                "key_count_total": self.key_count_total,
            },
            "mouse": {
                "avg_speed_px_ms": self.avg_speed_px_ms,
                "std_speed_px_ms": self.std_speed_px_ms,
                "click_count_total": self.click_count_total,
            },
            "session": {
                "time_to_first_interaction_ms": self.time_to_first_interaction_ms,
                "paste_count_per_session": self.paste_count_per_session,
                "tab_switches_per_session": self.tab_switches_per_session,
            },
            "bot_indicators": {
                "zero_mouse_movement_rate": self.zero_mouse_movement_rate,
                "constant_typing_rate": self.constant_typing_rate,
                "no_scroll_rate": self.no_scroll_rate,
            },
            "sample_count": self.sample_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_signals(
        cls,
        tenant_id: str,
        entity_id: str,
        device_id: str,
        behavior: dict[str, Any],
    ) -> BiometricProfile:
        """Create profile from SDK behavior signals."""
        now = time.time()
        typing = behavior.get("typing") or {}
        mouse = behavior.get("mouse") or {}
        session = behavior.get("session") or {}
        bot = behavior.get("bot_indicators") or {}

        return cls(
            entity_id=entity_id,
            device_id=device_id,
            tenant_id=tenant_id,
            avg_inter_key_ms=float(typing.get("avg_inter_key_ms", 0)),
            std_inter_key_ms=float(typing.get("std_inter_key_ms", 0)),
            avg_hold_ms=float(typing.get("avg_hold_ms", 0)),
            key_count_total=int(typing.get("key_count", 0)),
            avg_speed_px_ms=float(mouse.get("avg_speed_px_ms", 0)),
            std_speed_px_ms=float(mouse.get("std_speed_px_ms", 0)),
            click_count_total=int(mouse.get("click_count", 0)),
            time_to_first_interaction_ms=float(
                session.get("time_to_first_interaction_ms", -1)
            ),
            paste_count_per_session=float(session.get("paste_count", 0)),
            tab_switches_per_session=float(session.get("tab_switches", 0)),
            zero_mouse_movement_rate=float(bot.get("zero_mouse_movement", False)),
            constant_typing_rate=float(bot.get("constant_typing_speed", False)),
            no_scroll_rate=float(bot.get("no_scroll", False)),
            sample_count=1,
            first_seen=now,
            last_seen=now,
        )

    def merge(self, other: BiometricProfile) -> BiometricProfile:
        """Merge another profile, updating with weighted averages."""
        n1 = self.sample_count
        n2 = other.sample_count
        n_total = n1 + n2

        def weighted_avg(v1: float, v2: float) -> float:
            if n_total == 0:
                return 0.0
            return (v1 * n1 + v2 * n2) / n_total

        # Welford's algorithm for combined standard deviation
        def combined_std(std1: float, std2: float, mean1: float, mean2: float) -> float:
            if n_total <= 1:
                return 0.0
            # Pooled variance approximation
            var1 = std1**2
            var2 = std2**2
            pooled_var = (n1 * var1 + n2 * var2) / n_total
            # Add correction for mean difference
            mean_diff = (mean1 - mean2) ** 2
            correction = (n1 * n2 * mean_diff) / (n_total**2)
            return math.sqrt(max(0.0, pooled_var + correction))

        return BiometricProfile(
            entity_id=self.entity_id,
            device_id=self.device_id,
            tenant_id=self.tenant_id,
            avg_inter_key_ms=weighted_avg(
                self.avg_inter_key_ms, other.avg_inter_key_ms
            ),
            std_inter_key_ms=combined_std(
                self.std_inter_key_ms,
                other.std_inter_key_ms,
                self.avg_inter_key_ms,
                other.avg_inter_key_ms,
            ),
            avg_hold_ms=weighted_avg(self.avg_hold_ms, other.avg_hold_ms),
            key_count_total=self.key_count_total + other.key_count_total,
            avg_speed_px_ms=weighted_avg(self.avg_speed_px_ms, other.avg_speed_px_ms),
            std_speed_px_ms=combined_std(
                self.std_speed_px_ms,
                other.std_speed_px_ms,
                self.avg_speed_px_ms,
                other.avg_speed_px_ms,
            ),
            click_count_total=self.click_count_total + other.click_count_total,
            time_to_first_interaction_ms=weighted_avg(
                self.time_to_first_interaction_ms,
                other.time_to_first_interaction_ms,
            ),
            paste_count_per_session=weighted_avg(
                self.paste_count_per_session,
                other.paste_count_per_session,
            ),
            tab_switches_per_session=weighted_avg(
                self.tab_switches_per_session,
                other.tab_switches_per_session,
            ),
            zero_mouse_movement_rate=weighted_avg(
                self.zero_mouse_movement_rate,
                other.zero_mouse_movement_rate,
            ),
            constant_typing_rate=weighted_avg(
                self.constant_typing_rate,
                other.constant_typing_rate,
            ),
            no_scroll_rate=weighted_avg(self.no_scroll_rate, other.no_scroll_rate),
            sample_count=n_total,
            first_seen=min(self.first_seen, other.first_seen),
            last_seen=max(self.last_seen, other.last_seen),
        )


@dataclass
class DeviceReputation:
    """Device reputation score based on fraud history."""

    device_id: str
    tenant_id: str

    # Risk metrics
    total_evaluations: int
    fraud_confirmed_count: int
    review_count: int
    deny_count: int

    # Score components
    base_reputation: float  # 0-100, higher is better
    velocity_risk: float  # 0-100, higher is riskier

    # Consortium data
    cross_tenant_appearances: int

    # Metadata
    first_seen: float
    last_seen: float
    known_fraud_tenants: set[str] = field(default_factory=set)

    def calculate_risk_score(self) -> float:
        """Calculate overall risk score (0-100, higher = riskier)."""
        if self.total_evaluations == 0:
            return 50.0  # Unknown = neutral

        # Base fraud rate
        fraud_rate = self.fraud_confirmed_count / self.total_evaluations

        # Weight by volume (more data = more confident)
        confidence = min(1.0, self.total_evaluations / 100)

        # Consortium penalty
        consortium_penalty = min(25.0, self.cross_tenant_appearances * 5)
        if self.known_fraud_tenants:
            consortium_penalty += len(self.known_fraud_tenants) * 10

        base_score = (fraud_rate * 100) * confidence + (50 * (1 - confidence))
        return min(100.0, base_score + consortium_penalty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "tenant_id": self.tenant_id,
            "evaluations": {
                "total": self.total_evaluations,
                "fraud_confirmed": self.fraud_confirmed_count,
                "review": self.review_count,
                "deny": self.deny_count,
            },
            "reputation": {
                "base": round(self.base_reputation, 2),
                "velocity_risk": round(self.velocity_risk, 2),
                "calculated_risk_score": round(self.calculate_risk_score(), 2),
            },
            "consortium": {
                "cross_tenant_appearances": self.cross_tenant_appearances,
                "known_fraud_tenants": sorted(self.known_fraud_tenants),
            },
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


class DeviceIntelligenceStore:
    """Redis-backed device intelligence store."""

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    def set_client(self, client: aioredis.Redis) -> None:
        self._client = client

    def _biometric_key(self, tenant_id: str, entity_id: str, device_id: str) -> str:
        return f"{BIOMETRIC_PREFIX}{tenant_id}:{entity_id}:{device_id}"

    def _devrep_key(self, tenant_id: str, device_id: str) -> str:
        return f"{DEVICE_REP_PREFIX}{tenant_id}:{device_id}"

    def _consortium_key(self, device_id: str) -> str:
        """Cross-tenant consortium tracking for a device."""
        return f"{CONSORTIUM_DEVICE_PREFIX}{device_id}"

    def _ip_velocity_key(self, device_id: str, ip: str) -> str:
        return f"{DEVICE_IP_VELOCITY_PREFIX}{device_id}:{ip}"

    async def record_biometrics(
        self,
        tenant_id: str,
        entity_id: str,
        device_id: str,
        behavior: dict[str, Any],
    ) -> BiometricProfile:
        """Record behavioral biometrics, merging with existing profile."""
        if not self._client:
            raise RuntimeError("Redis client not initialized")

        key = self._biometric_key(tenant_id, entity_id, device_id)

        # Get existing profile
        existing_raw = await self._client.get(key)
        new_profile = BiometricProfile.from_signals(
            tenant_id, entity_id, device_id, behavior
        )

        if existing_raw:
            existing_dict = json.loads(existing_raw)
            existing = BiometricProfile(
                entity_id=existing_dict["entity_id"],
                device_id=existing_dict["device_id"],
                tenant_id=existing_dict["tenant_id"],
                avg_inter_key_ms=existing_dict["typing"]["avg_inter_key_ms"],
                std_inter_key_ms=existing_dict["typing"]["std_inter_key_ms"],
                avg_hold_ms=existing_dict["typing"]["avg_hold_ms"],
                key_count_total=existing_dict["typing"]["key_count_total"],
                avg_speed_px_ms=existing_dict["mouse"]["avg_speed_px_ms"],
                std_speed_px_ms=existing_dict["mouse"]["std_speed_px_ms"],
                click_count_total=existing_dict["mouse"]["click_count_total"],
                time_to_first_interaction_ms=existing_dict["session"][
                    "time_to_first_interaction_ms"
                ],
                paste_count_per_session=existing_dict["session"][
                    "paste_count_per_session"
                ],
                tab_switches_per_session=existing_dict["session"][
                    "tab_switches_per_session"
                ],
                zero_mouse_movement_rate=existing_dict["bot_indicators"][
                    "zero_mouse_movement_rate"
                ],
                constant_typing_rate=existing_dict["bot_indicators"][
                    "constant_typing_rate"
                ],
                no_scroll_rate=existing_dict["bot_indicators"]["no_scroll_rate"],
                sample_count=existing_dict["sample_count"],
                first_seen=existing_dict["first_seen"],
                last_seen=existing_dict["last_seen"],
            )
            merged = existing.merge(new_profile)
        else:
            merged = new_profile

        await self._client.setex(key, BIOMETRIC_TTL, json.dumps(merged.to_dict()))
        return merged

    async def get_biometric_profile(
        self, tenant_id: str, entity_id: str, device_id: str
    ) -> BiometricProfile | None:
        """Get behavioral biometric profile for a device."""
        if not self._client:
            return None

        key = self._biometric_key(tenant_id, entity_id, device_id)
        raw = await self._client.get(key)
        if not raw:
            return None

        data = json.loads(raw)
        return BiometricProfile(
            entity_id=data["entity_id"],
            device_id=data["device_id"],
            tenant_id=data["tenant_id"],
            avg_inter_key_ms=data["typing"]["avg_inter_key_ms"],
            std_inter_key_ms=data["typing"]["std_inter_key_ms"],
            avg_hold_ms=data["typing"]["avg_hold_ms"],
            key_count_total=data["typing"]["key_count_total"],
            avg_speed_px_ms=data["mouse"]["avg_speed_px_ms"],
            std_speed_px_ms=data["mouse"]["std_speed_px_ms"],
            click_count_total=data["mouse"]["click_count_total"],
            time_to_first_interaction_ms=data["session"][
                "time_to_first_interaction_ms"
            ],
            paste_count_per_session=data["session"]["paste_count_per_session"],
            tab_switches_per_session=data["session"]["tab_switches_per_session"],
            zero_mouse_movement_rate=data["bot_indicators"]["zero_mouse_movement_rate"],
            constant_typing_rate=data["bot_indicators"]["constant_typing_rate"],
            no_scroll_rate=data["bot_indicators"]["no_scroll_rate"],
            sample_count=data["sample_count"],
            first_seen=data["first_seen"],
            last_seen=data["last_seen"],
        )

    async def update_device_reputation(
        self,
        tenant_id: str,
        device_id: str,
        decision: str,
        is_fraud_confirmed: bool = False,
    ) -> DeviceReputation:
        """Update device reputation based on decision outcome."""
        if not self._client:
            raise RuntimeError("Redis client not initialized")

        key = self._devrep_key(tenant_id, device_id)

        # Get existing reputation
        raw = await self._client.get(key)
        now = time.time()

        if raw:
            data = json.loads(raw)
            rep = DeviceReputation(
                device_id=device_id,
                tenant_id=tenant_id,
                total_evaluations=data["evaluations"]["total"],
                fraud_confirmed_count=data["evaluations"]["fraud_confirmed"],
                review_count=data["evaluations"]["review"],
                deny_count=data["evaluations"]["deny"],
                base_reputation=data["reputation"]["base"],
                velocity_risk=data["reputation"]["velocity_risk"],
                cross_tenant_appearances=data["consortium"]["cross_tenant_appearances"],
                known_fraud_tenants=set(data["consortium"]["known_fraud_tenants"]),
                first_seen=data["first_seen"],
                last_seen=now,
            )
        else:
            rep = DeviceReputation(
                device_id=device_id,
                tenant_id=tenant_id,
                total_evaluations=0,
                fraud_confirmed_count=0,
                review_count=0,
                deny_count=0,
                base_reputation=50.0,
                velocity_risk=50.0,
                cross_tenant_appearances=0,
                known_fraud_tenants=set(),
                first_seen=now,
                last_seen=now,
            )

        # Update counters
        rep.total_evaluations += 1
        if is_fraud_confirmed:
            rep.fraud_confirmed_count += 1
            rep.known_fraud_tenants.add(tenant_id)
        if decision == "review":
            rep.review_count += 1
        elif decision == "deny":
            rep.deny_count += 1

        # Update base reputation (decay fraud rate over time)
        fraud_rate = rep.fraud_confirmed_count / rep.total_evaluations
        rep.base_reputation = 100 - (fraud_rate * 100)

        await self._client.setex(key, DEVICE_REP_TTL, json.dumps(rep.to_dict()))
        return rep

    async def get_device_reputation(
        self, tenant_id: str, device_id: str
    ) -> DeviceReputation | None:
        """Get device reputation."""
        if not self._client:
            return None

        key = self._devrep_key(tenant_id, device_id)
        raw = await self._client.get(key)
        if not raw:
            return None

        data = json.loads(raw)
        return DeviceReputation(
            device_id=device_id,
            tenant_id=tenant_id,
            total_evaluations=data["evaluations"]["total"],
            fraud_confirmed_count=data["evaluations"]["fraud_confirmed"],
            review_count=data["evaluations"]["review"],
            deny_count=data["evaluations"]["deny"],
            base_reputation=data["reputation"]["base"],
            velocity_risk=data["reputation"]["velocity_risk"],
            cross_tenant_appearances=data["consortium"]["cross_tenant_appearances"],
            known_fraud_tenants=set(data["consortium"]["known_fraud_tenants"]),
            first_seen=data["first_seen"],
            last_seen=data["last_seen"],
        )

    async def record_consortium_device(
        self, device_id: str, tenant_id: str, entity_id: str
    ) -> dict[str, Any]:
        """Record device appearance for consortium cross-tenant detection."""
        if not self._client:
            return {"tenant_count": 0, "entity_count": 0}

        key = self._consortium_key(device_id)
        now = time.time()

        # Add tenant to set
        await self._client.sadd(f"{key}:tenants", tenant_id)
        await self._client.expire(f"{key}:tenants", DEVICE_REP_TTL)

        # Add entity (with timestamp in sorted set)
        await self._client.zadd(f"{key}:entities", {f"{tenant_id}:{entity_id}": now})
        await self._client.expire(f"{key}:entities", DEVICE_REP_TTL)

        # Get stats
        tenant_count = await self._client.scard(f"{key}:tenants")
        entity_count = await self._client.zcard(f"{key}:entities")

        return {
            "device_id": device_id,
            "tenant_count": tenant_count,
            "entity_count": entity_count,
            "is_shared": tenant_count > 1,
        }

    async def get_consortium_device_info(self, device_id: str) -> dict[str, Any] | None:
        """Get consortium information for a device."""
        if not self._client:
            return None

        key = self._consortium_key(device_id)

        tenant_count = await self._client.scard(f"{key}:tenants")
        if tenant_count == 0:
            return None

        entity_count = await self._client.zcard(f"{key}:entities")
        tenants = await self._client.smembers(f"{key}:tenants")

        return {
            "device_id": device_id,
            "tenant_count": tenant_count,
            "entity_count": entity_count,
            "is_shared": tenant_count > 1,
            "tenants": [t.decode() if isinstance(t, bytes) else t for t in tenants],
        }

    async def record_device_ip_velocity(
        self, device_id: str, ip: str, tenant_id: str
    ) -> dict[str, Any]:
        """Record device-to-IP mapping for velocity tracking."""
        if not self._client:
            return {"unique_ips_24h": 0, "unique_tenants_24h": 0}

        key = self._ip_velocity_key(device_id, ip)
        now = time.time()

        # Record this IP appearance
        await self._client.zadd(
            f"{DEVICE_IP_VELOCITY_PREFIX}{device_id}:ips", {ip: now}
        )
        await self._client.expire(
            f"{DEVICE_IP_VELOCITY_PREFIX}{device_id}:ips", IP_VELOCITY_TTL
        )

        # Record tenant appearance from this IP
        await self._client.sadd(f"{key}:tenants", tenant_id)
        await self._client.expire(f"{key}:tenants", IP_VELOCITY_TTL)

        # Count unique IPs in last 24h
        day_ago = now - 86400
        unique_ips = await self._client.zcount(
            f"{DEVICE_IP_VELOCITY_PREFIX}{device_id}:ips", day_ago, "+inf"
        )

        # Count unique tenants
        unique_tenants = await self._client.scard(f"{key}:tenants")

        return {
            "device_id": device_id,
            "ip": ip,
            "unique_ips_24h": unique_ips,
            "unique_tenants_24h": unique_tenants,
            "velocity_risk": "high"
            if unique_ips > 5
            else "medium"
            if unique_ips > 2
            else "low",
        }

    async def get_device_intelligence_summary(
        self, tenant_id: str, entity_id: str, device_id: str
    ) -> dict[str, Any]:
        """Get comprehensive device intelligence summary."""
        bio = await self.get_biometric_profile(tenant_id, entity_id, device_id)
        rep = await self.get_device_reputation(tenant_id, device_id)
        consortium = await self.get_consortium_device_info(device_id)

        risk_factors: list[str] = []
        risk_score = 50.0

        # Biometric risk
        if bio:
            if bio.zero_mouse_movement_rate > 0.5:
                risk_factors.append("high_bot_indicator_rate")
                risk_score += 15
            if bio.constant_typing_rate > 0.5:
                risk_factors.append("suspicious_typing_pattern")
                risk_score += 10

        # Reputation risk
        if rep:
            risk_score = rep.calculate_risk_score()
            if rep.fraud_confirmed_count > 0:
                risk_factors.append("prior_fraud_history")
            if rep.cross_tenant_appearances > 2:
                risk_factors.append("high_velocity_device")

        # Consortium risk
        if consortium and consortium.get("is_shared"):
            risk_factors.append("shared_cross_tenant_device")
            risk_score += 20

        return {
            "device_id": device_id,
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "risk_score": min(100.0, risk_score),
            "risk_factors": risk_factors,
            "has_biometric_profile": bio is not None,
            "has_reputation_history": rep is not None,
            "is_consortium_shared": consortium.get("is_shared", False)
            if consortium
            else False,
            "biometrics": bio.to_dict() if bio else None,
            "reputation": rep.to_dict() if rep else None,
            "consortium": consortium,
        }


device_intelligence = DeviceIntelligenceStore()
