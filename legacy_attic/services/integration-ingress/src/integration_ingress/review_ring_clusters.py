"""Review ring clusters — users who all reviewed the same five products (Prompt 185)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

SHARED_PRODUCT_COUNT = 5
DEFAULT_MIN_RING_SIZE = 3
DEFAULT_CLUSTER_LIMIT = 12


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _product_catalog(seed: str) -> list[dict[str, Any]]:
    """Five shared products for a cluster — deterministic from cluster seed."""
    titles = [
        "Wireless noise-canceling earbuds",
        "USB-C fast charger 65W",
        "Ergonomic desk lamp",
        "Stainless steel water bottle",
        "Bluetooth mechanical keyboard",
    ]
    categories = ["electronics", "electronics", "home", "home", "electronics"]
    products: list[dict[str, Any]] = []
    for i in range(SHARED_PRODUCT_COUNT):
        pid = f"prod_{seed}_{i}"
        products.append(
            {
                "product_id": pid,
                "title": titles[i],
                "category": categories[i],
                "seller_id": f"seller_{seed[:6]}_{i % 2}",
            },
        )
    return products


def _member_row(
    cluster_seed: str,
    member_index: int,
    *,
    tenant_id: str,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    seed = hashlib.sha256(f"{tenant_id}:{cluster_seed}:member:{member_index}".encode()).hexdigest()
    uid = f"reviewer_{seed[:10]}"
    base = datetime.now(UTC) - timedelta(days=14 + member_index)
    reviews = [
        {
            "product_id": p["product_id"],
            "rating": 4 + (int(seed[i * 2 : i * 2 + 2], 16) % 2),
            "reviewed_at": (base + timedelta(hours=i * 5 + member_index)).isoformat(),
        }
        for i, p in enumerate(products)
    ]
    ratings = [int(r["rating"]) for r in reviews]
    return {
        "user_id": uid,
        "display_name": f"Reviewer {member_index + 1}",
        "shared_product_count": len(products),
        "avg_rating_given": round(sum(ratings) / len(ratings), 2),
        "reviews": reviews,
        "first_shared_review_at": reviews[0]["reviewed_at"],
        "last_shared_review_at": reviews[-1]["reviewed_at"],
        "device_id": f"dev_{seed[10:16]}",
    }


def _cluster_row(index: int, *, tenant_id: str, min_ring_size: int) -> dict[str, Any]:
    cluster_seed = hashlib.sha256(f"{tenant_id}:review_ring:{index}".encode()).hexdigest()[:12]
    products = _product_catalog(cluster_seed)
    member_count = min_ring_size + (int(cluster_seed[0:2], 16) % 5)
    members = [
        _member_row(cluster_seed, m, tenant_id=tenant_id, products=products)
        for m in range(member_count)
    ]

    device_ids = [str(m.get("device_id")) for m in members]
    unique_devices = len(set(device_ids))
    device_overlap = member_count - unique_devices
    suspicion = min(
        99,
        40 + member_count * 6 + device_overlap * 8 + (10 if member_count >= 6 else 0),
    )

    return {
        "cluster_id": f"rr_{cluster_seed}",
        "shared_products": products,
        "shared_product_ids": [p["product_id"] for p in products],
        "member_count": member_count,
        "members": members,
        "suspicion_score": suspicion,
        "signals": _cluster_signals(member_count, device_overlap),
        "detected_at": (datetime.now(UTC) - timedelta(hours=index * 6)).isoformat(),
    }


def _cluster_signals(member_count: int, device_overlap: int) -> list[str]:
    signals: list[str] = ["exact_five_product_review_overlap"]
    if member_count >= 5:
        signals.append("large_review_ring")
    if device_overlap >= 2:
        signals.append("shared_device_fingerprint_across_reviewers")
    if member_count >= 4 and device_overlap >= 1:
        signals.append("coordinated_review_ring")
    return signals


def build_review_ring_payload(
    *,
    tenant_id: str,
    min_ring_size: int = DEFAULT_MIN_RING_SIZE,
    limit: int = DEFAULT_CLUSTER_LIMIT,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    min_size = max(2, min(int(min_ring_size), 20))
    lim = max(3, min(int(limit), 50))

    clusters = [_cluster_row(i, tenant_id=tid, min_ring_size=min_size) for i in range(lim)]
    clusters = [c for c in clusters if int(c["member_count"]) >= min_size]
    clusters_sorted = sorted(
        clusters, key=lambda c: (-int(c["suspicion_score"]), -int(c["member_count"]))
    )

    total_users = sum(int(c["member_count"]) for c in clusters_sorted)
    high_suspicion = sum(1 for c in clusters_sorted if int(c["suspicion_score"]) >= 70)

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "rules": {
            "shared_product_count": SHARED_PRODUCT_COUNT,
            "min_ring_size": min_size,
        },
        "summary": {
            "cluster_count": len(clusters_sorted),
            "users_in_rings": total_users,
            "high_suspicion_clusters": high_suspicion,
            "largest_ring_size": max((int(c["member_count"]) for c in clusters_sorted), default=0),
        },
        "signals": [
            f"{len(clusters_sorted)} review ring(s) with identical {SHARED_PRODUCT_COUNT}-product overlap",
        ]
        if clusters_sorted
        else [],
        "clusters": clusters_sorted,
    }
