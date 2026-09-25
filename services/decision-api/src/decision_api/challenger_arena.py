"""Challenger bus + bake-off arena (P2): governed A/B of N challengers.

Any external score, model, or pack can be wired as a named challenger and
evaluated in SHADOW against the same features the champion saw. Iron rules
preserved: challengers never decide, never Promote, land on the receipt after
packs (audit-only). Labels unknown => metric unknown (never 0).

Backed by ``evaluate_json_rules`` in ``evaluation_mode="challenger"`` so the
arena exercises the same engine the champion would — no second evaluator to
drift.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from decision_api.json_rules import evaluate_adhoc_packs_json

log = logging.getLogger("decision-api.challenger_arena")

ARENA_SCHEMA_ID = "tarka.challenger_arena/v1"


class ArenaConfig:
    """Named challengers for one tenant. Each challenger is a JSON rule pack
    (same schema the desk authors). Store/round-trip via JSON dicts."""

    def __init__(self, tenant_id: str, challengers: dict[str, dict[str, Any]]):
        self.tenant_id = tenant_id
        self.challengers = challengers

    @classmethod
    def from_store(cls, data: dict[str, Any]) -> "ArenaConfig":
        challengers = {}
        raw = data.get("challengers") or {}
        if isinstance(raw, dict):
            for name, pack in raw.items():
                if isinstance(pack, dict):
                    challengers[str(name)] = pack
        return cls(tenant_id=str(data.get("tenant_id") or ""), challengers=challengers)

    def to_store(self) -> dict[str, Any]:
        return {
            "schema_id": ARENA_SCHEMA_ID,
            "tenant_id": self.tenant_id,
            "challengers": {k: v for k, v in self.challengers.items()},
        }


def _challenger_delta(
    pack: dict[str, Any],
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str,
    entity_id: str | None,
    signal_tags: list[str] | None,
) -> tuple[float, list[str]]:
    """Evaluate one challenger pack via the shared engine, challenger mode.

    Uses the ad-hoc pack path (same Rust/Python engine, challenger mode) so
    the arena exercises exactly what a promoted pack would — no drift.
    """
    rules, _tags, delta, hits = evaluate_adhoc_packs_json(
        [pack],
        features,
        redis_tags,
        tenant_id,
        entity_id,
        signal_tags=signal_tags,
    )
    return float(delta), list(rules or hits or [])


def evaluate_arena(
    config: ArenaConfig,
    *,
    features: dict[str, Any],
    redis_tags: list[str],
    champion_decision: str,
    champion_score: float,
    entity_id: str | None = None,
    signal_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Run every configured challenger in shadow; report per-challenger
    score/decision/divergence. Production decision passes through untouched."""
    from decision_api.evaluate.pipeline import decision_from_rule_score

    out: dict[str, Any] = {
        "schema_id": ARENA_SCHEMA_ID,
        "tenant_id": config.tenant_id,
        "mode": "shadow",
        "production_decision": champion_decision,
        "champion_score": float(champion_score),
        "challengers": {},
    }
    for name, pack in config.challengers.items():
        delta, hits = _challenger_delta(
            pack,
            features,
            redis_tags,
            config.tenant_id,
            entity_id,
            signal_tags,
        )
        score = 10.0 + delta
        decision = decision_from_rule_score(score)
        out["challengers"][name] = {
            "score": score,
            "decision": decision,
            "rule_hits": hits,
            "diverges_from_champion": decision != champion_decision,
        }
    return out


def weekly_champion_report(
    tenant_id: str,
    ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reduce an arena ledger (per-evaluate shadow records) to a weekly
    champion report: n, divergence_rate, fp_delta per challenger.

    fp_delta = challenger_fp_rate - champion_fp_rate over labeled rows only;
    None (unknown) when a challenger has no labeled rows. Labels unknown =>
    unknown, never zero.
    """
    per: dict[str, dict[str, Any]] = {}
    n = len(ledger)
    for row in ledger:
        champ = row.get("champion") or {}
        champ_label = champ.get("label")
        for name, ch in (row.get("challengers") or {}).items():
            slot = per.setdefault(
                name, {"n": 0, "divergent": 0, "labeled": 0, "champ_fp": 0, "ch_fp": 0}
            )
            slot["n"] += 1
            if ch.get("decision") != champ.get("decision"):
                slot["divergent"] += 1
            label = ch.get("label")
            if label is not None and champ_label is not None:
                slot["labeled"] += 1
                if champ_label == "fraud" and champ.get("decision") == "allow":
                    slot["champ_fp"] += 1
                if label == "legit" and ch.get("decision") == "deny":
                    slot["ch_fp"] += 1
    challengers_out: dict[str, Any] = {}
    for name, s in per.items():
        challengers_out[name] = {
            "n": s["n"],
            "divergence_rate": (s["divergent"] / s["n"]) if s["n"] else None,
            "fp_delta": (
                (s["ch_fp"] / s["labeled"]) - (s["champ_fp"] / s["labeled"])
                if s["labeled"]
                else None
            ),
        }
    return {
        "schema_id": "tarka.challenger_report/v1",
        "tenant_id": tenant_id,
        "n": n,
        "challengers": challengers_out,
    }


# ---------- last mile: config + ledger (doc 13 step 1) ----------

_LEDGER_RING_MAX = 3_000


def _arena_rules_dir() -> "Path":
    """Arena configs live beside calibration data under rules/arena/."""
    from decision_api.calibration_api import data_dir

    return data_dir().parent / "arena"


def _arena_ledger_path(tenant_id: str) -> "Path":
    from decision_api.calibration_api import data_dir

    return data_dir() / f"arena_ledger_{tenant_id}.jsonl"


def load_arena_config(tenant_id: str) -> ArenaConfig | None:
    """Load rules/arena/<tenant>.json; missing file = arena off (None)."""
    import json as _json

    safe = "".join(c for c in tenant_id if c.isalnum() or c in "-_")[:64]
    if not safe:
        return None
    path = _arena_rules_dir() / f"{safe}.json"
    if not path.is_file():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("arena_config_unreadable tenant=%s", tenant_id)
        return None
    if not isinstance(data, dict):
        return None
    cfg = ArenaConfig.from_store(data)
    return cfg if cfg.challengers else None


def record_arena_row(tenant_id: str, arena_out: dict) -> bool:
    """Append one shadow row to the tenant's jsonl ledger. Fail-soft, ring-bounded."""
    import json as _json
    import time

    try:
        path = _arena_ledger_path(tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(arena_out)
        row.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row) + "\n")
        # ring bound: trim head beyond the row cap (cheap check, rare rewrite)
        try:
            lines = [
                x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()
            ]
            if len(lines) > _LEDGER_RING_MAX:
                keep = lines[-_LEDGER_RING_MAX:]
                path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError:
            pass
        return True
    except Exception:
        log.debug("arena_ledger_write_failed tenant=%s", tenant_id, exc_info=True)
        return False


def _maybe_arena_snapshot(
    *,
    tenant_id: str,
    features: dict,
    redis_tags: list,
    champion_decision: str,
    champion_score: float,
    entity_id: str | None = None,
    signal_tags: list | None = None,
) -> dict | None:
    """Pipeline seam: evaluate + record when the tenant has an arena config.

    Returns the arena output when recorded, None when arena is off. Fail-soft
    end to end: an arena problem must never break or delay evaluate.
    """
    try:
        cfg = load_arena_config(tenant_id)
        if cfg is None:
            return None
        out = evaluate_arena(
            cfg,
            features=features,
            redis_tags=redis_tags,
            champion_decision=champion_decision,
            champion_score=champion_score,
            entity_id=entity_id,
            signal_tags=signal_tags,
        )
        record_arena_row(tenant_id, out)
        return out
    except Exception:
        log.debug("arena_snapshot_failed tenant=%s", tenant_id, exc_info=True)
        return None
