"""Server-side behavioral biometrics analyzer.

Takes raw behavior data collected by the TypeScript SDK's BehaviorCollector
and computes risk indicators for fraud detection.
"""

from __future__ import annotations

import math
from typing import Any


class BehaviorAnalyzer:
    """Analyzes behavioral biometrics data from client-side collection.

    Usage::

        result = BehaviorAnalyzer.analyze(behavior_data)
        # result = {
        #     "is_bot_likely": True,
        #     "behavior_risk_score": 85,
        #     "anomalies": ["zero_mouse_movement", "constant_typing_speed"]
        # }
    """

    _BOT_INDICATOR_WEIGHTS: dict[str, int] = {
        "zero_mouse_movement": 30,
        "constant_typing_speed": 25,
        "no_scroll": 15,
        "suspiciously_fast": 30,
    }

    @staticmethod
    def analyze(behavior_data: dict[str, Any]) -> dict[str, Any]:
        if not behavior_data:
            return {
                "is_bot_likely": False,
                "behavior_risk_score": 0,
                "anomalies": [],
            }

        anomalies: list[str] = []
        risk_score = 0

        bot = behavior_data.get("bot_indicators") or {}
        for indicator, weight in BehaviorAnalyzer._BOT_INDICATOR_WEIGHTS.items():
            if bot.get(indicator):
                anomalies.append(indicator)
                risk_score += weight

        session = behavior_data.get("session") or {}
        typing = behavior_data.get("typing") or {}
        mouse = behavior_data.get("mouse") or {}
        touch = behavior_data.get("touch") or {}

        paste_count = session.get("paste_count", 0)
        if paste_count > 3:
            anomalies.append("heavy_paste_usage")
            risk_score += min(15, paste_count * 3)

        tab_switches = session.get("tab_switches", 0)
        if tab_switches > 10:
            anomalies.append("excessive_tab_switching")
            risk_score += min(10, tab_switches)

        time_to_first = session.get("time_to_first_interaction_ms", -1)
        if time_to_first >= 0 and time_to_first < 100:
            anomalies.append("instant_interaction")
            risk_score += 10

        avg_inter_key = typing.get("avg_inter_key_ms", 999)
        key_count = typing.get("key_count", 0)
        if avg_inter_key < 25 and key_count > 30:
            anomalies.append("superhuman_typing_speed")
            risk_score += 15

        std_inter_key = typing.get("std_inter_key_ms", 999)
        if std_inter_key < 3 and key_count > 20:
            anomalies.append("robotic_typing_rhythm")
            risk_score += 10

        avg_hold = typing.get("avg_hold_ms", 0)
        if key_count > 10 and avg_hold < 10:
            anomalies.append("abnormally_short_key_holds")
            risk_score += 10

        mouse_std = mouse.get("std_speed_px_ms", 0)
        click_count = mouse.get("click_count", 0)
        if click_count > 10 and mouse_std < 0.01:
            anomalies.append("uniform_mouse_speed")
            risk_score += 10

        touch_count = touch.get("touch_count", 0)
        avg_force = touch.get("avg_force", 0)
        if touch_count > 5 and avg_force > 0 and _is_constant_force(avg_force, behavior_data):
            anomalies.append("constant_touch_pressure")
            risk_score += 10

        risk_score = max(0, min(100, risk_score))

        is_bot_likely = risk_score >= 50 or sum(1 for i in bot.values() if i) >= 2

        return {
            "is_bot_likely": is_bot_likely,
            "behavior_risk_score": risk_score,
            "anomalies": anomalies,
        }


def _is_constant_force(avg_force: float, behavior_data: dict[str, Any]) -> bool:
    """Heuristic: if the average force is exactly 1.0 it's likely simulated."""
    return math.isclose(avg_force, 1.0, abs_tol=0.01)
