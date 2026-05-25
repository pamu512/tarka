"""ReportLab PDF bundle for dispute filing: JSON evidence plus a two-hop graph diagram."""

from __future__ import annotations

import io
import json
import math
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, Paragraph, Preformatted, SimpleDocTemplate, Spacer

# Gate / human-visible marker (also drawn as vector labels in :class:`_GraphVizFlowable`).
PDF_GRAPH_SECTION_TITLE = "Evidence graph (two-hop network visualization)"


def _json_pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


class _GraphVizFlowable(Flowable):
    """Simple node–link sketch from normalized ``build_graph_viz`` output."""

    def __init__(self, graph_viz: dict[str, Any]) -> None:
        super().__init__()
        self._viz = graph_viz

    def wrap(self, avail_width: float, _avail_height: float) -> tuple[float, float]:
        self._width = min(float(avail_width), 520.0)
        return (self._width, 230.0)

    def draw(self) -> None:
        c = self.canv
        w, h = self._width, 230.0
        c.setFont("Helvetica-Bold", 11)
        c.drawString(8, h - 16, PDF_GRAPH_SECTION_TITLE)

        nodes: list[dict[str, str]] = list(self._viz.get("nodes") or [])
        links: list[dict[str, str]] = list(self._viz.get("links") or [])
        if not nodes:
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(8, h / 2, "No graph nodes for this anchor.")
            return

        cx = w / 2.0
        cy = h / 2.0 - 8.0
        positions: dict[str, tuple[float, float]] = {}
        anchor_id = nodes[0]["id"]
        positions[anchor_id] = (cx, cy)
        others = [n for n in nodes if n.get("id") != anchor_id]
        n_other = len(others)
        for i, n in enumerate(others):
            ang = (2.0 * math.pi * i / n_other) if n_other else 0.0
            rid = str(n.get("id", ""))
            positions[rid] = (cx + 72.0 * math.cos(ang), cy + 72.0 * math.sin(ang))

        c.setStrokeColor(colors.grey)
        for lk in links:
            s, t = lk.get("source"), lk.get("target")
            if s in positions and t in positions:
                x0, y0 = positions[s]
                x1, y1 = positions[t]
                c.line(x0, y0, x1, y1)

        for nid, (x, y) in positions.items():
            fill = (
                colors.HexColor("#1a5276")
                if nid.startswith("user:")
                else colors.HexColor("#1e8449")
            )
            if nid.startswith("ip:"):
                fill = colors.HexColor("#b9770e")
            c.setFillColor(fill)
            c.circle(x, y, 9, stroke=1, fill=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 7)
            lbl = ""
            for n in nodes:
                if n.get("id") == nid:
                    lbl = str(n.get("label", nid))[:28]
                    break
            c.drawString(max(8, x - 36), y + 14, lbl)


def build_dispute_evidence_pdf_bytes(
    *,
    case_doc: dict[str, Any],
    graph_doc: dict[str, Any] | list[Any] | None,
    rust_doc: dict[str, Any],
    graph_viz: dict[str, Any],
) -> bytes:
    """Synchronous PDF build (call from ``asyncio.to_thread`` from async handlers)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=inch * 0.75,
        leftMargin=inch * 0.75,
        topMargin=inch * 0.75,
        bottomMargin=inch * 0.75,
        title="Dispute evidence package",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="DisputeTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )
    h2 = ParagraphStyle(name="DisputeH2", parent=styles["Heading2"], fontSize=12, spaceAfter=6)
    mono = ParagraphStyle(
        name="DisputeMono",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=7,
        leading=9,
    )
    story: list[Any] = [
        Paragraph("Dispute evidence package", title_style),
        Paragraph(
            f"Generated (UTC): {datetime.now(UTC).isoformat()}",
            styles["Normal"],
        ),
        Spacer(1, 0.15 * inch),
        Paragraph("Lifecycle and shadow case (JSON)", h2),
        Preformatted(_json_pretty(case_doc), mono, maxLineLength=110),
        Spacer(1, 0.12 * inch),
        Paragraph("Shadow graph snapshot (JSON)", h2),
        Preformatted(
            _json_pretty(graph_doc if graph_doc is not None else {}), mono, maxLineLength=110
        ),
        Spacer(1, 0.12 * inch),
        Paragraph("Rule-engine trace (JSON)", h2),
        Preformatted(_json_pretty(rust_doc), mono, maxLineLength=110),
        Spacer(1, 0.18 * inch),
        Paragraph(
            "The diagram below is derived from the live two-hop neighbor network for the case anchor "
            "(<b>user_link_key</b>), not only the frozen shadow snapshot.",
            styles["Normal"],
        ),
        Spacer(1, 0.1 * inch),
        _GraphVizFlowable(graph_viz),
    ]
    doc.build(story)
    return buf.getvalue()
