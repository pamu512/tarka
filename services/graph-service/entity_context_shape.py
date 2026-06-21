"""Derive UI-oriented deep entity context from graph neighborhood nodes (JanusGraph / Neo4j)."""

from __future__ import annotations

import re
from typing import Any

_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def shape_deep_context_from_nodes(
    entity_id: str, tenant_id: str, nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build ``historical_transactions`` / ``ip_addresses`` from subgraph-style nodes.

    ``nodes`` items match the public subgraph contract: ``id``, ``labels``, ``properties``.
    """
    historical_transactions: list[dict[str, Any]] = []
    ip_addresses: list[dict[str, Any]] = []
    seen_ip: set[str] = set()

    for n in nodes:
        nid = str(n.get("id") or "")
        labels_raw = n.get("labels") or []
        labels = [str(x) for x in labels_raw] if isinstance(labels_raw, list) else [str(labels_raw)]
        lc = {x.lower() for x in labels}
        props = n.get("properties") if isinstance(n.get("properties"), dict) else {}

        if "payment" in lc:
            historical_transactions.append(
                {
                    "external_id": nid,
                    "trace_id": props.get("trace_id"),
                    "amount": props.get("amount"),
                    "currency": props.get("currency"),
                    "decision": props.get("decision"),
                    "ip": props.get("ip") or props.get("client_ip"),
                    "occurred_at": props.get("occurred_at")
                    or props.get("created_at")
                    or props.get("timestamp"),
                }
            )

        for key in ("client_ip", "ip_address", "src_ip", "ip"):
            val = props.get(key)
            if isinstance(val, str):
                s = val.strip()
                if _IPV4.match(s) and s not in seen_ip:
                    seen_ip.add(s)
                    ip_addresses.append(
                        {
                            "ip": s,
                            "source": f"property:{key}",
                            "last_seen": props.get("last_seen") or props.get("updated_at"),
                            "event_count": 1,
                        }
                    )

        if _IPV4.match(nid) and nid not in seen_ip:
            seen_ip.add(nid)
            ip_addresses.append(
                {
                    "ip": nid,
                    "source": "vertex_external_id",
                    "last_seen": None,
                    "event_count": 1,
                }
            )

    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "historical_transactions": historical_transactions[:100],
        "ip_addresses": ip_addresses[:80],
    }
