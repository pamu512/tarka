from __future__ import annotations

from pathlib import Path


def test_no_orphaned_shared_path_fragments_in_core_files():
    root = Path(__file__).resolve().parents[3]
    targets = [
        root / "services/decision-api/src/decision_api/main.py",
        root / "services/decision-api/src/decision_api/rule_api.py",
        root / "services/decision-api/src/decision_api/compliance_api.py",
        root / "services/case-api/src/case_api/main.py",
        root / "services/case-api/src/case_api/dispute_api.py",
        root / "services/event-ingest/src/event_ingest/main.py",
        root / "services/analytics-sink/src/analytics_sink/main.py",
    ]

    bad_snippets = [
        ', "..", "..", "..", "..", "shared"))',
        "if str(_shared) not in sys.path:",
        "if _shared_dir not in sys.path:",
    ]

    offenders: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for snippet in bad_snippets:
            if snippet in text:
                offenders.append(f"{path}: {snippet}")

    assert not offenders, "Found broken shared-import refactor fragments:\\n" + "\\n".join(offenders)

