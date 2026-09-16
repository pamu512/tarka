"""DSAR must include the graph's personal data when the graph is wired.

Access/portability previously exported SQL audit rows only; the entity's graph
profile (nodes, one-hop edges, risk properties) is personal data under GDPR and
must ride the same export. Fail-soft: when the graph is unwired or the hop
fails, the SQL export still returns with an honest note instead of silently
omitting the graph.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_SRC = Path(__file__).resolve().parents[1]
for _p in (_SRC / "src", _SRC.parent / "shared", _SRC.parents[2] / "packages/shared-core"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


_GRAPH_EXPORT = {
    "entity_id": "u1",
    "nodes": [{"id": "u1", "label": "Person"}],
    "edges": [],
}


class TestGraphInclusionInDSAR(unittest.IsolatedAsyncioTestCase):
    async def test_access_includes_graph_export_when_wired(self) -> None:
        from decision_api.compliance_api import _graph_subject_export

        with patch(
            "decision_api.compliance_api._fetch_graph_export", AsyncMock(return_value=_GRAPH_EXPORT)
        ):
            block = await _graph_subject_export("t1", "u1", graph_url="http://graph:8001")
        self.assertEqual(block["status"], "included")
        self.assertEqual(block["export"], _GRAPH_EXPORT)

    async def test_access_notes_absence_when_unwired(self) -> None:
        from decision_api.compliance_api import _graph_subject_export

        block = await _graph_subject_export("t1", "u1", graph_url="")
        self.assertEqual(block["status"], "not_configured")

    async def test_access_failsoft_on_hop_failure(self) -> None:
        from decision_api.compliance_api import _graph_subject_export

        async def _boom(*_a, **_k):
            raise RuntimeError("graph down")

        with patch("decision_api.compliance_api._fetch_graph_export", _boom):
            block = await _graph_subject_export("t1", "u1", graph_url="http://graph:8001")
        self.assertEqual(block["status"], "unavailable")
        self.assertIn("reason", block)


if __name__ == "__main__":
    unittest.main()
