from __future__ import annotations

from io import BytesIO

from collaboration_chat_bridge.attachments import extract_text_from_bytes
from openpyxl import Workbook


def test_extract_xlsx_basic():
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Data"
    ws.append(["a", "b"])
    ws.append([1, 2])
    buf = BytesIO()
    wb.save(buf)
    data = buf.getvalue()

    text = extract_text_from_bytes(
        data,
        filename="report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert "Sheet: Data" in text
    assert "a" in text and "b" in text
    assert "1" in text and "2" in text
