"""Guard: the ``tarka.events.labels`` transport is gone; the retro-tagging work stays.

The consortium reader was removed earlier; with no consumer, the JetStream publish
tail only held live label-propagation work hostage to NATS availability (handlers
raised post-completion and re-ran the whole outbox row forever). This pins the
prune: module absent, subject string absent from source, handlers must not
reference the publisher. If a consumer for the subject ever lands, reintroduce
the publisher then — with a reader.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_ORCH = _REPO / "services/orchestrator"
_SUBJECT = "tarka.events.labels"


class TestLabelsBusRemoved(unittest.TestCase):
    def test_labels_jetstream_module_is_gone(self) -> None:
        import importlib

        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("messaging.labels_jetstream")

    def test_subject_string_absent_from_source(self) -> None:
        offenders: list[str] = []
        for path in _ORCH.rglob("*.py"):
            resolved = path.resolve()
            if resolved == Path(__file__).resolve():
                continue
            text = path.read_text(errors="replace")
            if _SUBJECT in text:
                offenders.append(str(path.relative_to(_REPO)))
        self.assertEqual(offenders, [])

    def test_handlers_do_not_reference_publisher(self) -> None:
        for name in ("label_propagator.py", "shadow_retro_tag.py"):
            text = (_ORCH / "workers/handlers" / name).read_text()
            self.assertNotIn("publish_normalized_label_enriched", text, name)
            self.assertNotIn("build_label_bus_emit_dict", text, name)

    def test_stream_registration_dropped_subject(self) -> None:
        text = (_ORCH / "messaging/nats_jetstream.py").read_text()
        self.assertNotIn("labels", text.lower())


if __name__ == "__main__":
    unittest.main()
