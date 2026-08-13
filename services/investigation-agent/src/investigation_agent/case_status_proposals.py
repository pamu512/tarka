"""Graph-gated case status proposals. Confirm/ack does not call orchestrator PUT."""

from __future__ import annotations

import time
import uuid
from typing import Any

from investigation_agent import agent_run_store

_ALLOWED = frozenset({"OPEN", "UNDER_REVIEW", "PENDING_ACTION", "RESOLVED_FRAUD", "RESOLVED_LEGIT"})
_ACK_STATUSES = frozenset({"confirmed", "rejected"})


class GraphRequiredError(Exception):
    """Proposal requires graph freshness on the linked AgentRun."""


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "proposal_id": row[0],
        "tenant_id": row[1],
        "case_id": row[2],
        "agent_run_id": row[3],
        "from_status": row[4],
        "to_status": row[5],
        "reason_code": row[6],
        "status": row[7],
        "created_at": row[8],
    }


def insert_proposal(
    *,
    tenant_id: str,
    case_id: str,
    agent_run_id: str,
    from_status: str,
    to_status: str,
    reason_code: str,
) -> str:
    to_st = (to_status or "").strip()
    if to_st == "RESOLVED_AUTO" or to_st not in _ALLOWED:
        raise ValueError(f"invalid to_status: {to_st}")
    run = agent_run_store.get_agent_run(run_id=agent_run_id, tenant_id=tenant_id)
    if run is None or run.get("graph_missing"):
        raise GraphRequiredError("graph_required")
    if (run.get("case_id") or "").strip() != (case_id or "").strip():
        raise ValueError("case_id_mismatch")
    pid = str(uuid.uuid4())
    c = agent_run_store._get_conn()
    now = time.time()
    with agent_run_store._lock:
        c.execute(
            """
            INSERT INTO case_status_proposals (
                proposal_id, tenant_id, case_id, agent_run_id,
                from_status, to_status, reason_code, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                pid,
                (tenant_id or "").strip(),
                (case_id or "").strip(),
                (agent_run_id or "").strip(),
                (from_status or "").strip(),
                to_st,
                (reason_code or "").strip(),
                now,
            ),
        )
        c.commit()
    return pid


def list_proposals(case_id: str, tenant_id: str) -> list[dict[str, Any]]:
    cid = (case_id or "").strip()
    tid = (tenant_id or "").strip()
    if not cid or not tid:
        return []
    c = agent_run_store._get_conn()
    rows = c.execute(
        """
        SELECT proposal_id, tenant_id, case_id, agent_run_id,
               from_status, to_status, reason_code, status, created_at
        FROM case_status_proposals
        WHERE case_id = ? AND tenant_id = ?
        ORDER BY created_at DESC
        """,
        (cid, tid),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def ack_proposal(proposal_id: str, tenant_id: str, status: str) -> dict[str, Any] | None:
    pid = (proposal_id or "").strip()
    tid = (tenant_id or "").strip()
    st = (status or "").strip()
    if not pid or not tid:
        return None
    if st not in _ACK_STATUSES:
        raise ValueError("status must be confirmed or rejected")
    c = agent_run_store._get_conn()
    with agent_run_store._lock:
        row = c.execute(
            """
            SELECT proposal_id, tenant_id, case_id, agent_run_id,
                   from_status, to_status, reason_code, status, created_at
            FROM case_status_proposals
            WHERE proposal_id = ? AND tenant_id = ?
            """,
            (pid, tid),
        ).fetchone()
        if not row:
            return None
        current = row[7]
        if current != "pending":
            raise ValueError("proposal_not_pending")
        c.execute(
            "UPDATE case_status_proposals SET status = ? WHERE proposal_id = ? AND tenant_id = ?",
            (st, pid, tid),
        )
        c.commit()
        updated = c.execute(
            """
            SELECT proposal_id, tenant_id, case_id, agent_run_id,
                   from_status, to_status, reason_code, status, created_at
            FROM case_status_proposals
            WHERE proposal_id = ? AND tenant_id = ?
            """,
            (pid, tid),
        ).fetchone()
    return _row_to_dict(updated) if updated else None
