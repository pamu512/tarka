"""Guard: the ``TARKA_EVENTS`` stream (``tarka.events.graph`` / ``tarka.events.velocity``) is gone.

The subjects were declared in ``messaging/nats_jetstream.py`` with no producer or
consumer anywhere in the repo. This pins the prune: module absent, subject strings
absent from source, retention settings dropped from config, and the lifespan keeps
the NATS connect plus the live ``shadow.investigate`` stream ensure. If a consumer
for these subjects ever lands, reintroduce the stream then — with a publisher.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_ORCH = _REPO / "services/orchestrator"
_SUBJECTS = ("tarka.events.graph", "tarka.events.velocity")


class TestTarkaEventsStreamRemoved(unittest.TestCase):
    def test_jetstream_module_is_gone(self) -> None:
        import importlib

        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("messaging.nats_jetstream")

    def test_subject_strings_absent_from_source(self) -> None:
        offenders: list[str] = []
        for path in _ORCH.rglob("*.py"):
            resolved = path.resolve()
            if resolved == Path(__file__).resolve():
                continue
            text = path.read_text(errors="replace")
            for subject in _SUBJECTS:
                if subject in text:
                    offenders.append(f"{path.relative_to(_REPO)}:{subject}")
        self.assertEqual(offenders, [])

    def test_tarka_events_settings_dropped(self) -> None:
        text = (_ORCH / "config.py").read_text()
        self.assertNotIn("TARKA_EVENTS_STREAM_NAME", text)
        self.assertNotIn("tarka_events_jetstream", text)

    def test_lifespan_keeps_shadow_stream_bootstrap(self) -> None:
        text = (_ORCH / "lifespan.py").read_text()
        self.assertNotIn("TarkaEventsJetStreamInitializer", text)
        self.assertIn("ensure_shadow_investigate_stream", text)
        self.assertIn("nats.connect", text)


if __name__ == "__main__":
    unittest.main()
