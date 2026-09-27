"""Self-test: the signal-catalog drift gate actually trips (P3.3 companion)."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

GATE = Path(__file__).resolve().parent / "check_signal_catalog.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("gate_under_test", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load gate module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SignalCatalogGateSelfTest(unittest.TestCase):
    def test_gate_fails_on_undocumented_tag(self):
        """A mintable tag missing from the doc must FAIL the gate."""
        mod = _load_gate()
        with (
            mock.patch.object(
                mod, "mintable_tags", lambda: {"behavior:no_mouse", "behavior:drift_probe"}
            ),
            mock.patch.object(mod, "documented_tags", lambda: {"behavior:no_mouse"}),
        ):
            rc = mod.main()
        self.assertEqual(rc, 1, "gate must exit 1 on undocumented mintable tag")

    def test_gate_fails_on_aspirational_doc_row(self):
        """A doc row naming an unmintable tag must FAIL the gate."""
        mod = _load_gate()
        with (
            mock.patch.object(mod, "mintable_tags", lambda: {"behavior:no_mouse"}),
            mock.patch.object(
                mod, "documented_tags", lambda: {"behavior:no_mouse", "behavior:vaporware"}
            ),
        ):
            rc = mod.main()
        self.assertEqual(rc, 1, "gate must exit 1 on aspirational doc row")

    def test_gate_passes_in_sync(self):
        mod = _load_gate()
        with (
            mock.patch.object(mod, "mintable_tags", lambda: {"behavior:no_mouse"}),
            mock.patch.object(mod, "documented_tags", lambda: {"behavior:no_mouse"}),
        ):
            rc = mod.main()
        self.assertEqual(rc, 0, "gate must exit 0 when in sync")


if __name__ == "__main__":
    unittest.main()
