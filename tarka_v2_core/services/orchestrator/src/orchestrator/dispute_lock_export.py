"""File dispute: transition lifecycle case to locked queue state and emit a ReportLab evidence PDF."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.case_export import fetch_compliance_export_documents
from orchestrator.dispute_evidence_pdf import build_dispute_evidence_pdf_bytes
from orchestrator.entity_profile import build_graph_viz
from orchestrator.graph.client import GraphClient

# Audit ``case_history.reason_code`` for the final dispute lock transition.
FILE_DISPUTE_LOCK_REASON = "FILE_DISPUTE_FINAL_LOCK"


async def build_dispute_evidence_pdf_for_case(
    *,
    audit_session_factory: async_sessionmaker[AsyncSession],
    case_id: str,
    graph_client: GraphClient,
) -> bytes:
    """
    Assemble the same evidence as compliance ZIP export plus a two-hop graph diagram (ReportLab).

    Caller is responsible for having applied the lifecycle lock transition first.
    """
    case_doc, graph_doc, rust_doc = await fetch_compliance_export_documents(
        audit_session_factory=audit_session_factory,
        case_id=case_id,
    )
    ukey = str(case_doc["lifecycle_case"]["user_link_key"])
    network = await graph_client.two_hop_neighbor_network(ukey)
    viz = build_graph_viz(ukey, network)
    return await asyncio.to_thread(
        build_dispute_evidence_pdf_bytes,
        case_doc=case_doc,
        graph_doc=graph_doc,
        rust_doc=rust_doc,
        graph_viz=viz,
    )
