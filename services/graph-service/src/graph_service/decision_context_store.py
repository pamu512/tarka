"""Decision context graph — SQLite system of record for accountability decisions.

ponytail: SQLite under DECISION_GRAPH_DB_PATH is the accountability SoR for v1.
Janus Decision vertices are an optional mirror for subgraph UX (Wave 2+), not required
for chain/impact/search. Ceiling: single-writer process; upgrade path is Postgres.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_CAUSAL_RELS = frozenset({"CAUSED", "INFLUENCED", "PRECEDENT_FOR", "SUPERSEDES"})
_BASED_ON = "BASED_ON"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _db_path() -> Path:
    raw = (os.environ.get("DECISION_GRAPH_DB_PATH") or "").strip()
    if raw:
        return Path(raw)
    base = (os.environ.get("GRAPH_DATA_DIR") or "").strip() or "/tmp/tarka-graph"
    return Path(base) / "decision_context.sqlite"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            tenant_id TEXT NOT NULL,
            external_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            category TEXT NOT NULL,
            scenario TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reasoning TEXT NOT NULL DEFAULT '',
            confidence REAL,
            rule_ids_json TEXT NOT NULL DEFAULT '[]',
            audit_log_id TEXT,
            agent_run_id TEXT,
            case_id TEXT,
            trace_id TEXT,
            entity_external_ids_json TEXT NOT NULL DEFAULT '[]',
            evidence_ids_json TEXT NOT NULL DEFAULT '[]',
            shadow INTEGER NOT NULL DEFAULT 0,
            semantica_decision_id TEXT,
            created_at TEXT NOT NULL,
            invalidated_at TEXT,
            invalidation_reason TEXT,
            PRIMARY KEY (tenant_id, external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_tenant_created
            ON decisions(tenant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_decisions_tenant_entity
            ON decisions(tenant_id, entity_external_ids_json);
        CREATE TABLE IF NOT EXISTS decision_edges (
            tenant_id TEXT NOT NULL,
            from_external_id TEXT NOT NULL,
            to_external_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, from_external_id, to_external_id, relationship)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_to
            ON decision_edges(tenant_id, to_external_id);
        CREATE INDEX IF NOT EXISTS idx_edges_from
            ON decision_edges(tenant_id, from_external_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_trace
            ON decisions(tenant_id, trace_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_decisions_case
            ON decisions(tenant_id, case_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_decisions_kind
            ON decisions(tenant_id, kind, created_at);
        """
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["rule_ids"] = json.loads(d.pop("rule_ids_json") or "[]")
    d["entity_external_ids"] = json.loads(d.pop("entity_external_ids_json") or "[]")
    d["evidence_ids"] = json.loads(d.pop("evidence_ids_json") or "[]")
    d["shadow"] = bool(d.get("shadow"))
    return d


def record_decision(
    *,
    tenant_id: str,
    kind: str,
    category: str,
    scenario: str,
    outcome: str,
    reasoning: str = "",
    confidence: float | None = None,
    rule_ids: list[str] | None = None,
    audit_log_id: str | None = None,
    agent_run_id: str | None = None,
    case_id: str | None = None,
    trace_id: str | None = None,
    entity_external_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    shadow: bool = False,
    external_id: str | None = None,
    semantica_decision_id: str | None = None,
) -> str:
    tid = (tenant_id or "").strip()
    if not tid:
        raise ValueError("tenant_id required")
    did = (external_id or "").strip() or f"dec_{uuid.uuid4().hex}"
    now = _utcnow()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO decisions (
                    tenant_id, external_id, kind, category, scenario, outcome, reasoning,
                    confidence, rule_ids_json, audit_log_id, agent_run_id, case_id, trace_id,
                    entity_external_ids_json, evidence_ids_json, shadow, semantica_decision_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, external_id) DO UPDATE SET
                    kind=excluded.kind,
                    category=excluded.category,
                    scenario=excluded.scenario,
                    outcome=excluded.outcome,
                    reasoning=excluded.reasoning,
                    confidence=excluded.confidence,
                    rule_ids_json=excluded.rule_ids_json,
                    audit_log_id=COALESCE(excluded.audit_log_id, decisions.audit_log_id),
                    agent_run_id=COALESCE(excluded.agent_run_id, decisions.agent_run_id),
                    case_id=COALESCE(excluded.case_id, decisions.case_id),
                    trace_id=COALESCE(excluded.trace_id, decisions.trace_id),
                    entity_external_ids_json=excluded.entity_external_ids_json,
                    evidence_ids_json=excluded.evidence_ids_json,
                    shadow=excluded.shadow,
                    semantica_decision_id=COALESCE(
                        excluded.semantica_decision_id, decisions.semantica_decision_id
                    )
                """,
                (
                    tid,
                    did,
                    str(kind),
                    str(category),
                    str(scenario),
                    str(outcome),
                    str(reasoning or ""),
                    confidence,
                    json.dumps(list(rule_ids or [])),
                    audit_log_id,
                    agent_run_id,
                    case_id,
                    trace_id,
                    json.dumps(list(entity_external_ids or [])),
                    json.dumps(list(evidence_ids or [])),
                    1 if shadow else 0,
                    semantica_decision_id,
                    now,
                ),
            )
            # BASED_ON edges to entity ids (logical; entities may live in Janus)
            for eid in entity_external_ids or []:
                ee = str(eid).strip()
                if not ee:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO decision_edges
                    (tenant_id, from_external_id, to_external_id, relationship, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tid, did, ee, _BASED_ON, now),
                )
            conn.commit()
        finally:
            conn.close()
    return did


def add_edge(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
) -> None:
    tid = (tenant_id or "").strip()
    rel = str(relationship or "").upper().replace(" ", "_").replace("-", "_")
    if rel not in _CAUSAL_RELS and rel != _BASED_ON:
        raise ValueError(f"unsupported relationship: {relationship}")
    frm = str(from_external_id or "").strip()
    to = str(to_external_id or "").strip()
    if not tid or not frm or not to:
        raise ValueError("tenant_id, from_external_id, to_external_id required")
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO decision_edges
                (tenant_id, from_external_id, to_external_id, relationship, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tid, frm, to, rel, _utcnow()),
            )
            conn.commit()
        finally:
            conn.close()


def get_decision(tenant_id: str, external_id: str) -> dict[str, Any] | None:
    tid = (tenant_id or "").strip()
    did = (external_id or "").strip()
    if not tid or not did:
        return None
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM decisions WHERE tenant_id=? AND external_id=?",
                (tid, did),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()


def set_semantica_decision_id(tenant_id: str, external_id: str, semantica_decision_id: str) -> None:
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute(
                """
                UPDATE decisions SET semantica_decision_id=?
                WHERE tenant_id=? AND external_id=?
                """,
                (semantica_decision_id, tenant_id, external_id),
            )
            conn.commit()
        finally:
            conn.close()


def invalidate_decision(
    tenant_id: str,
    external_id: str,
    reason: str,
    *,
    supersede_to: str | None = None,
) -> dict[str, Any] | None:
    tid = (tenant_id or "").strip()
    did = (external_id or "").strip()
    now = _utcnow()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute(
                """
                UPDATE decisions
                SET invalidated_at=?, invalidation_reason=?
                WHERE tenant_id=? AND external_id=?
                """,
                (now, str(reason or ""), tid, did),
            )
            conn.commit()
        finally:
            conn.close()
    replacement = (supersede_to or "").strip()
    if replacement:
        add_edge(tid, replacement, did, "SUPERSEDES")
    row = get_decision(tid, did)
    return row


def find_latest(
    tenant_id: str,
    *,
    kind: str | None = None,
    trace_id: str | None = None,
    case_id: str | None = None,
    entity_external_id: str | None = None,
    agent_run_id: str | None = None,
    exclude_external_id: str | None = None,
) -> dict[str, Any] | None:
    hits = search_decisions(
        tenant_id=tenant_id,
        kind=kind,
        trace_id=trace_id,
        case_id=case_id,
        entity_external_id=entity_external_id,
        agent_run_id=agent_run_id,
        exclude_external_id=exclude_external_id,
        limit=1,
    )
    return hits[0] if hits else None


def get_neighbor_summary(tenant_id: str, external_id: str) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    did = (external_id or "").strip()
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            inbound = conn.execute(
                """
                SELECT relationship, from_external_id
                FROM decision_edges WHERE tenant_id=? AND to_external_id=?
                """,
                (tid, did),
            ).fetchall()
            outbound = conn.execute(
                """
                SELECT relationship, to_external_id
                FROM decision_edges WHERE tenant_id=? AND from_external_id=?
                """,
                (tid, did),
            ).fetchall()
        finally:
            conn.close()
    return {
        "inbound": [
            {"relationship": r["relationship"], "from_external_id": r["from_external_id"]}
            for r in inbound
        ],
        "outbound": [
            {"relationship": r["relationship"], "to_external_id": r["to_external_id"]}
            for r in outbound
        ],
    }


def search_decisions(
    *,
    tenant_id: str,
    entity_external_id: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    kind: str | None = None,
    trace_id: str | None = None,
    case_id: str | None = None,
    agent_run_id: str | None = None,
    q: str | None = None,
    since: str | None = None,
    until: str | None = None,
    exclude_external_id: str | None = None,
    include_invalidated: bool = True,
    limit: int = 20,
) -> list[dict[str, Any]]:
    tid = (tenant_id or "").strip()
    lim = max(1, min(int(limit or 20), 100))
    clauses = ["tenant_id=?"]
    params: list[Any] = [tid]
    if entity_external_id:
        clauses.append("entity_external_ids_json LIKE ?")
        params.append(f"%{json.dumps(str(entity_external_id).strip())[1:-1]}%")
    if category:
        clauses.append("category=?")
        params.append(str(category))
    if outcome:
        clauses.append("outcome=?")
        params.append(str(outcome))
    if kind:
        clauses.append("kind=?")
        params.append(str(kind))
    if trace_id:
        clauses.append("trace_id=?")
        params.append(str(trace_id).strip())
    if case_id:
        clauses.append("case_id=?")
        params.append(str(case_id).strip())
    if agent_run_id:
        clauses.append("agent_run_id=?")
        params.append(str(agent_run_id).strip())
    if not include_invalidated:
        clauses.append("invalidated_at IS NULL")
    if exclude_external_id:
        clauses.append("external_id != ?")
        params.append(str(exclude_external_id).strip())
    if since:
        clauses.append("created_at >= ?")
        params.append(str(since))
    if until:
        clauses.append("created_at <= ?")
        params.append(str(until))
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        clauses.append("(lower(scenario) LIKE ? OR lower(reasoning) LIKE ?)")
        params.extend([needle, needle])
    sql = f"SELECT * FROM decisions WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?"
    params.append(lim)
    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()


def _jaccard(left: list[Any] | None, right: list[Any] | None) -> float:
    a = {str(x).strip() for x in (left or []) if str(x).strip()}
    b = {str(x).strip() for x in (right or []) if str(x).strip()}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_precedent(
    probe: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, dict[str, float]]:
    """Deterministic overlap score. Embeddings stay off (DECISION_GRAPH_PRECEDENT_EMBEDDINGS unused)."""
    entity = _jaccard(probe.get("entity_external_ids"), candidate.get("entity_external_ids"))
    rules = _jaccard(probe.get("rule_ids"), candidate.get("rule_ids"))
    category = (
        1.0
        if (probe.get("category") and probe.get("category") == candidate.get("category"))
        else 0.0
    )
    outcome = (
        1.0 if (probe.get("outcome") and probe.get("outcome") == candidate.get("outcome")) else 0.0
    )
    kind = 1.0 if (probe.get("kind") and probe.get("kind") == candidate.get("kind")) else 0.0
    breakdown = {
        "entity": round(entity * 4.0, 4),
        "rules": round(rules * 3.0, 4),
        "category": round(category * 2.0, 4),
        "outcome": round(outcome * 2.0, 4),
        "kind": round(kind * 1.0, 4),
    }
    return round(sum(breakdown.values()), 4), breakdown


def rank_precedents(
    *,
    tenant_id: str,
    from_external_id: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    kind: str | None = None,
    entity_external_ids: list[str] | None = None,
    rule_ids: list[str] | None = None,
    include_invalidated: bool = False,
    limit: int = 10,
    pool_limit: int = 200,
) -> list[dict[str, Any]]:
    """Rank similar decisions by entity/category/outcome/rule overlap. No embeddings."""
    probe: dict[str, Any] = {
        "category": (category or "").strip() or None,
        "outcome": (outcome or "").strip() or None,
        "kind": (kind or "").strip() or None,
        "entity_external_ids": [
            str(x).strip() for x in (entity_external_ids or []) if str(x).strip()
        ],
        "rule_ids": [str(x).strip() for x in (rule_ids or []) if str(x).strip()],
    }
    exclude = (from_external_id or "").strip() or None
    if exclude:
        source = get_decision(tenant_id, exclude)
        if source is None:
            return []
        probe = {
            "category": probe["category"] or source.get("category"),
            "outcome": probe["outcome"] or source.get("outcome"),
            "kind": probe["kind"] or source.get("kind"),
            "entity_external_ids": probe["entity_external_ids"]
            or list(source.get("entity_external_ids") or []),
            "rule_ids": probe["rule_ids"] or list(source.get("rule_ids") or []),
        }
    candidates = search_decisions(
        tenant_id=tenant_id,
        include_invalidated=include_invalidated,
        exclude_external_id=exclude,
        limit=max(1, min(int(pool_limit or 200), 500)),
    )
    ranked: list[dict[str, Any]] = []
    for row in candidates:
        score, breakdown = score_precedent(probe, row)
        if score <= 0:
            continue
        ranked.append({**row, "score": score, "score_breakdown": breakdown})
    ranked.sort(key=lambda r: (float(r["score"]), str(r.get("created_at") or "")), reverse=True)
    return ranked[: max(1, min(int(limit or 10), 50))]


def _walk(
    tenant_id: str,
    start_id: str,
    *,
    direction: str,
    max_depth: int,
) -> dict[str, Any]:
    """direction=inbound: edges pointing TO current (parents). outbound: FROM current (children)."""
    tid = (tenant_id or "").strip()
    start = (start_id or "").strip()
    depth_cap = max(1, min(int(max_depth or 5), 20))
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen_edge: set[tuple[str, str, str]] = set()

    with _LOCK:
        conn = _connect()
        try:
            _ensure_schema(conn)
            root = conn.execute(
                "SELECT * FROM decisions WHERE tenant_id=? AND external_id=?",
                (tid, start),
            ).fetchone()
            if not root:
                return {"nodes": [], "edges": []}
            nodes[start] = _row_to_dict(root)
            frontier = [start]
            for _ in range(depth_cap):
                nxt: list[str] = []
                for cur in frontier:
                    if direction == "inbound":
                        rows = conn.execute(
                            """
                            SELECT * FROM decision_edges
                            WHERE tenant_id=? AND to_external_id=?
                              AND relationship IN ('CAUSED','INFLUENCED','PRECEDENT_FOR','SUPERSEDES')
                            """,
                            (tid, cur),
                        ).fetchall()
                        for er in rows:
                            key = (er["from_external_id"], er["to_external_id"], er["relationship"])
                            if key in seen_edge:
                                continue
                            seen_edge.add(key)
                            edges.append(
                                {
                                    "from_external_id": er["from_external_id"],
                                    "to_external_id": er["to_external_id"],
                                    "relationship": er["relationship"],
                                }
                            )
                            parent = er["from_external_id"]
                            if parent not in nodes:
                                prow = conn.execute(
                                    "SELECT * FROM decisions WHERE tenant_id=? AND external_id=?",
                                    (tid, parent),
                                ).fetchone()
                                if prow:
                                    nodes[parent] = _row_to_dict(prow)
                                    nxt.append(parent)
                    else:
                        rows = conn.execute(
                            """
                            SELECT * FROM decision_edges
                            WHERE tenant_id=? AND from_external_id=?
                              AND relationship IN ('CAUSED','INFLUENCED','PRECEDENT_FOR','SUPERSEDES')
                            """,
                            (tid, cur),
                        ).fetchall()
                        for er in rows:
                            key = (er["from_external_id"], er["to_external_id"], er["relationship"])
                            if key in seen_edge:
                                continue
                            seen_edge.add(key)
                            edges.append(
                                {
                                    "from_external_id": er["from_external_id"],
                                    "to_external_id": er["to_external_id"],
                                    "relationship": er["relationship"],
                                }
                            )
                            child = er["to_external_id"]
                            if child not in nodes:
                                crow = conn.execute(
                                    "SELECT * FROM decisions WHERE tenant_id=? AND external_id=?",
                                    (tid, child),
                                ).fetchone()
                                if crow:
                                    nodes[child] = _row_to_dict(crow)
                                    nxt.append(child)
                frontier = nxt
                if not frontier:
                    break
        finally:
            conn.close()

    # chain order: start first, then BFS parents (for inbound)
    ordered: list[dict[str, Any]] = []
    if direction == "inbound":
        # reconstruct parent order: start, then walk edges reverse
        ordered.append(nodes[start])
        placed = {start}
        changed = True
        while changed:
            changed = False
            for e in edges:
                if e["to_external_id"] in placed and e["from_external_id"] not in placed:
                    pid = e["from_external_id"]
                    if pid in nodes:
                        ordered.append(nodes[pid])
                        placed.add(pid)
                        changed = True
        for nid, n in nodes.items():
            if nid not in placed:
                ordered.append(n)
    else:
        ordered.append(nodes[start])
        placed = {start}
        changed = True
        while changed:
            changed = False
            for e in edges:
                if e["from_external_id"] in placed and e["to_external_id"] not in placed:
                    cid = e["to_external_id"]
                    if cid in nodes:
                        ordered.append(nodes[cid])
                        placed.add(cid)
                        changed = True
        for nid, n in nodes.items():
            if nid not in placed:
                ordered.append(n)

    return {"nodes": ordered, "edges": edges}


def get_chain(tenant_id: str, external_id: str, max_depth: int = 5) -> dict[str, Any]:
    return _walk(tenant_id, external_id, direction="inbound", max_depth=max_depth)


def get_impact(tenant_id: str, external_id: str, max_depth: int = 5) -> dict[str, Any]:
    return _walk(tenant_id, external_id, direction="outbound", max_depth=max_depth)


def accountability_snapshot(
    tenant_id: str,
    *,
    case_id: str | None = None,
    trace_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Local SoR snapshot for bundles and compliance export."""
    seen: dict[str, dict[str, Any]] = {}
    for row in search_decisions(tenant_id=tenant_id, case_id=case_id, limit=limit):
        seen[row["external_id"]] = row
    if trace_id:
        for row in search_decisions(tenant_id=tenant_id, trace_id=trace_id, limit=limit):
            seen[row["external_id"]] = row
    decisions = sorted(seen.values(), key=lambda d: str(d.get("created_at") or ""))
    edges: list[dict[str, str]] = []
    for d in decisions:
        did = d["external_id"]
        for nb in get_neighbor_summary(tenant_id, did).get("inbound") or []:
            frm = nb.get("from_external_id")
            if frm in seen:
                edges.append(
                    {
                        "from_external_id": frm,
                        "to_external_id": did,
                        "relationship": nb.get("relationship"),
                    }
                )
    return {
        "schema_id": "tarka.decision_context/v1",
        "decisions": decisions,
        "edges": edges,
    }
