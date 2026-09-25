"""P3.4: observe-only behavior challenger pack (doc 13 Step 3, item 4).

The anti-Sardine demo: SDK behavior signals (bot indicators, typing, session)
landed in Observe as a shadow pack - never deciding until a human promotes.
"""

import json
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[1] / "rules"


def test_behavior_challenger_pack_exists_and_is_shadow():
    path = RULES_PATH / "behavior_challenger_v1.json"
    assert path.exists(), "behavior_challenger_v1.json missing from rules/"
    pack = json.loads(path.read_text(encoding="utf-8"))
    assert pack["mode"] == "shadow", "must land in Observe (shadow), never live"
    assert pack["name"], "shadow drafts are promoted by name"


def test_pack_rules_consume_real_behavior_tags():
    """Every any_tag the pack matches must be a tag extract_behavior_tags can mint."""
    from decision_api.main import extract_behavior_tags

    pack = json.loads(
        (RULES_PATH / "behavior_challenger_v1.json").read_text(encoding="utf-8")
    )
    referenced: set[str] = set()
    for tr in pack.get("tag_rules", []) or []:
        referenced.update(tr.get("any_tag", []) or [])
        referenced.update(tr.get("all_tags", []) or [])
    for r in pack.get("rules", []) or []:
        referenced.update(r.get("requires_tags", []) or [])
    assert referenced, "pack consumes no behavior tags - demo is hollow"

    # Synthesize device_context payloads that trip each extractor branch and
    # collect every tag the pipeline can actually mint.
    mintable = extract_behavior_tags(
        {
            "behavior": {
                "bot_indicators": {
                    "zero_mouse_movement": True,
                    "constant_typing_speed": True,
                    "no_scroll": True,
                    "suspiciously_fast": True,
                },
                "session": {"paste_count": 9, "tab_switches": 30},
                "typing": {"avg_inter_key_ms": 12, "key_count": 44},
            }
        }
    )
    mintable_set = set(mintable)
    missing = referenced - mintable_set
    assert not missing, (
        f"pack references tags the pipeline never mints: {sorted(missing)}"
    )


def test_pack_is_discoverable_as_shadow_draft():
    from decision_api.json_rules import get_shadow_packs, load_rules

    load_rules()  # disk packs load at service startup; tests must load explicitly
    names = [str(p.get("name") or "") for p in get_shadow_packs()]
    assert "behavior_challenger_v1" in names, "pack not discovered as a shadow draft"
