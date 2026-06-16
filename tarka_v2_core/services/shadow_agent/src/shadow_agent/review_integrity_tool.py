"""
Shadow tool: ``check_review_integrity(listing_id)`` — review-ring / social-engineering probe.

Uses Neo4j (same schema as :mod:`orchestrator.graph.client`): ``(User)-[:REVIEWED]->(Listing)``,
shared ``Device`` via ``USED_DEVICE``, shared ``IP`` via ``ORDERED_FROM_IP`` (User–asset–User
is a 2-hop path; direct shared asset is the operational signal).

Optional signup burst: DuckDB file from ``SHADOW_SIGNUPS_DUCKDB_PATH`` with table
``user_signups`` (columns ``user_id``, ``created_at``) unless overridden by env.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from ingestor.schemas import TransactionSchema

from shadow_agent.graph_hints import listing_id_from_transaction

logger = logging.getLogger(__name__)

LABEL_USER = "User"
LABEL_LISTING = "Listing"
LABEL_DEVICE = "Device"
LABEL_IP = "IP"
REL_REVIEWED = "REVIEWED"
REL_USED_DEVICE = "USED_DEVICE"
REL_ORDERED_FROM_IP = "ORDERED_FROM_IP"


def review_integrity_tool_mode() -> str:
    """``off`` | ``auto`` (default): run when ``listing_id`` is present on the transaction."""
    return (os.environ.get("SHADOW_REVIEW_INTEGRITY_MODE") or "auto").strip().lower()


def wants_check_review_integrity(
    tx: TransactionSchema,
    graph_context: dict[str, Any] | None,
) -> bool:
    if review_integrity_tool_mode() in ("off", "disabled", "false", "0"):
        return False
    if graph_context and isinstance(graph_context.get("check_review_integrity"), dict):
        return False
    return listing_id_from_transaction(tx) is not None


def should_invoke_check_review_integrity(
    tx: TransactionSchema,
    graph_context: dict[str, Any] | None,
    *,
    driver_available: bool,
) -> bool:
    return wants_check_review_integrity(tx, graph_context) and driver_available


def format_review_ring_summary(
    *,
    reviewer_count: int,
    hardware_overlap_count: int,
    hardware_kind: str,
    same_10min_burst: bool | None,
) -> str:
    """Human-readable line for prompts and ops logs (deterministic wording)."""
    burst = (
        "were created within a 10-minute burst"
        if same_10min_burst is True
        else (
            "did not all register inside one 10-minute window (per DuckDB)"
            if same_10min_burst is False
            else "signup timing could not be verified (DuckDB missing or incomplete rows)"
        )
    )
    if reviewer_count <= 0:
        return "No reviewers linked to this listing in the graph."
    if hardware_overlap_count <= 1 or reviewer_count <= 1:
        return (
            f"Listing has {reviewer_count} reviewer(s) in-graph; no multi-account hardware/IP "
            f"overlap detected among them. {burst.capitalize()}."
        )
    return (
        f"High probability of a review ring. {hardware_overlap_count} out of {reviewer_count} "
        f"reviewers share {hardware_kind} and {burst}."
    )


def _duckdb_same_10min_window(user_ids: list[str]) -> dict[str, Any]:
    path = (os.environ.get("SHADOW_SIGNUPS_DUCKDB_PATH") or "").strip()
    table = (os.environ.get("SHADOW_SIGNUPS_TABLE") or "user_signups").strip()
    col_user = (os.environ.get("SHADOW_SIGNUPS_USER_COL") or "user_id").strip()
    col_ts = (os.environ.get("SHADOW_SIGNUPS_TIME_COL") or "created_at").strip()
    out: dict[str, Any] = {
        "duckdb_path_configured": bool(path),
        "table": table,
        "all_reviewers_same_10min_window": None,
        "signup_span_seconds": None,
        "timestamps_iso": None,
    }
    if not path or not user_ids:
        return out
    try:
        import duckdb
    except ImportError:
        logger.warning("shadow_review_integrity_duckdb_import_failed")
        return out
    try:
        con = duckdb.connect(path, read_only=True)
    except Exception:
        logger.exception("shadow_review_integrity_duckdb_connect_failed path=%s", path)
        return out
    need = sorted(frozenset(user_ids))
    try:
        ph = ",".join(["?" for _ in need])
        q = (
            f'SELECT "{col_user}" AS uid, "{col_ts}" AS ts FROM "{table}" '
            f'WHERE "{col_user}" IN ({ph})'
        )
        rows = con.execute(q, need).fetchall()
    except Exception:
        logger.exception(
            "shadow_review_integrity_duckdb_query_failed table=%s",
            table,
        )
        try:
            con.close()
        except Exception:
            pass
        return out
    try:
        con.close()
    except Exception:
        pass

    parsed: list[tuple[str, datetime]] = []
    for uid, ts in rows:
        if uid is None:
            continue
        u = str(uid).strip()
        if not u:
            continue
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        else:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
        parsed.append((u, dt.astimezone(UTC)))

    by_user = {u: t for u, t in parsed}
    out["timestamps_iso"] = {u: by_user[u].isoformat() for u in sorted(by_user)}
    if len(by_user) < len(need):
        out["all_reviewers_same_10min_window"] = False
        out["signup_span_seconds"] = None
        return out
    times = [by_user[u] for u in need]
    span = max(times) - min(times)
    out["signup_span_seconds"] = span.total_seconds()
    out["all_reviewers_same_10min_window"] = span <= timedelta(minutes=10)
    return out


async def check_review_integrity(listing_id: str, driver: Any) -> dict[str, Any]:
    """
    Return structured review-integrity metrics for ``listing_id`` (Neo4j + optional DuckDB).
    """
    lid = listing_id.strip()
    if not lid:
        return {"error": "empty_listing_id"}

    q_reviewers = f"""
    MATCH (lst:`{LABEL_LISTING}` {{listing_id: $lid}})<-[:`{REL_REVIEWED}`]-(u:`{LABEL_USER}`)
    RETURN collect(DISTINCT u.user_id) AS reviewer_ids
    """

    q_devices = f"""
    MATCH (lst:`{LABEL_LISTING}` {{listing_id: $lid}})<-[:`{REL_REVIEWED}`]-(u:`{LABEL_USER}`)
    WITH collect(DISTINCT u.user_id) AS reviewer_ids
    WHERE size(reviewer_ids) >= 1
    UNWIND reviewer_ids AS rid
    MATCH (rx:`{LABEL_USER}` {{user_id: rid}})-[:`{REL_USED_DEVICE}`]->(d:`{LABEL_DEVICE}`)
    WITH d, collect(DISTINCT rid) AS users_on_device
    WHERE size(users_on_device) >= 2
    RETURN d.device_id AS device_id, users_on_device
    """

    q_ips = f"""
    MATCH (lst:`{LABEL_LISTING}` {{listing_id: $lid}})<-[:`{REL_REVIEWED}`]-(u:`{LABEL_USER}`)
    WITH collect(DISTINCT u.user_id) AS reviewer_ids
    WHERE size(reviewer_ids) >= 1
    UNWIND reviewer_ids AS rid
    MATCH (rx:`{LABEL_USER}` {{user_id: rid}})-[:`{REL_ORDERED_FROM_IP}`]->(ip:`{LABEL_IP}`)
    WITH ip, collect(DISTINCT rid) AS users_on_ip
    WHERE size(users_on_ip) >= 2
    RETURN ip.address AS ip_address, users_on_ip
    """

    async def work_reviewers(txn: Any) -> list[str]:
        result = await txn.run(q_reviewers, lid=lid)
        rec = await result.single()
        if rec is None:
            return []
        raw = rec.get("reviewer_ids") or []
        return [str(x) for x in raw if x is not None and str(x).strip()]

    async def work_devices(txn: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        result = await txn.run(q_devices, lid=lid)
        async for rec in result:
            out.append(
                {
                    "device_id": rec.get("device_id"),
                    "reviewer_user_ids": list(rec.get("users_on_device") or []),
                },
            )
        return out

    async def work_ips(txn: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        result = await txn.run(q_ips, lid=lid)
        async for rec in result:
            out.append(
                {
                    "ip_address": rec.get("ip_address"),
                    "reviewer_user_ids": list(rec.get("users_on_ip") or []),
                },
            )
        return out

    async with driver.session() as session:
        reviewer_ids = await session.execute_read(work_reviewers)
        shared_devices = await session.execute_read(work_devices)
        shared_ips = await session.execute_read(work_ips)

    hw_users: set[str] = set()
    for row in shared_devices:
        for u in row.get("reviewer_user_ids") or []:
            if u:
                hw_users.add(str(u))
    for row in shared_ips:
        for u in row.get("reviewer_user_ids") or []:
            if u:
                hw_users.add(str(u))

    signup = _duckdb_same_10min_window(reviewer_ids)
    burst = signup.get("all_reviewers_same_10min_window")

    n = len(reviewer_ids)
    overlap = len(hw_users)
    if shared_devices and not shared_ips:
        hw_kind = "a hardware hash (shared Device)"
    elif shared_ips and not shared_devices:
        hw_kind = "the same IP (shared IP node)"
    elif shared_devices and shared_ips:
        hw_kind = "hardware and/or IP (shared Device or IP nodes)"
    else:
        hw_kind = "hardware or IP"

    summary = format_review_ring_summary(
        reviewer_count=n,
        hardware_overlap_count=overlap,
        hardware_kind=hw_kind,
        same_10min_burst=burst if isinstance(burst, (bool, type(None))) else None,
    )

    review_ring_likely = n >= 2 and overlap >= 2 and (overlap / max(n, 1)) >= 0.4
    if burst is True and n >= 3:
        review_ring_likely = True

    return {
        "listing_id": lid,
        "reviewer_count": n,
        "reviewer_ids": sorted(reviewer_ids),
        "shared_devices": shared_devices,
        "shared_ips": shared_ips,
        "reviewers_sharing_device_or_ip_count": overlap,
        "signup_analysis": signup,
        "risk_summary": summary,
        "review_ring_likely": review_ring_likely,
    }
