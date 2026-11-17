"""Pure confidence-gate policy. Code owns side effects; Jev never authors the note."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from jev_system_one.client import SystemOneJudgment
from jev_system_one.pack import is_thin_evidence
from jev_system_one.questions import HAS_ENOUGH_SIGNAL, PACK_ID, REVIEW_PRIORITY

Gate = Literal["pass", "abstain", "skip_llm", "jev_error", "thin_evidence", "off"]


@dataclass(frozen=True)
class AdviseDecision:
    call_jev: bool
    call_llm: bool
    gate: Gate
    receipt: dict[str, Any] | None


def _receipt(
    *,
    mode: str,
    latency_ms: int,
    answers: dict[str, Any] | None,
    gate: Gate,
    llm_invoked: bool,
) -> dict[str, Any]:
    return {
        "pack": PACK_ID,
        "mode": mode,
        "latency_ms": max(0, int(latency_ms)),
        "answers": answers,
        "gate": gate,
        "llm_invoked": llm_invoked,
    }


def judgment_abstains(answers: dict[str, Any], min_confidence: float) -> bool:
    """Abstain on no-signal, low sufficiency confidence, or skip_noise.

    ``pattern_hint`` is display-only and does not gate the generative call.
    Confidence compared is ``has_enough_signal`` only. Threshold is strict ``<``.
    """
    signal = answers.get(HAS_ENOUGH_SIGNAL)
    priority = answers.get(REVIEW_PRIORITY)
    if not isinstance(signal, dict) or not isinstance(priority, dict):
        return True
    if signal.get("value") is not True:
        return True
    confidence = signal.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return True
    if float(confidence) < min_confidence:
        return True
    if priority.get("value") == "skip_noise":
        return True
    return False


def _active_mode(mode: str) -> Literal["shadow", "gate"] | None:
    if mode == "shadow":
        return "shadow"
    if mode == "gate":
        return "gate"
    return None


def _fail_closed(mode: Literal["shadow", "gate"], latency_ms: int) -> AdviseDecision:
    # Desk gate mode skips the LLM. Shadow still calls it and records jev_error.
    # Receipt gate stays jev_error (cause). llm_invoked is false only in gate mode,
    # which is the desk skip. ``skip_llm`` remains a valid gate literal for that skip
    # when a caller already stopped before a judgment; this function records the cause.
    call_llm = mode == "shadow"
    return AdviseDecision(
        call_jev=False,
        call_llm=call_llm,
        gate="jev_error",
        receipt=_receipt(
            mode=mode,
            latency_ms=latency_ms,
            answers=None,
            gate="jev_error",
            llm_invoked=call_llm,
        ),
    )


def preflight_advise(
    *,
    url: str,
    mode: str,
    pack: dict[str, Any] | None,
    question_pack: str = PACK_ID,
) -> AdviseDecision | None:
    """Terminal decision, or None when the caller must invoke System One.

    Empty URL and ``mode=off`` do not build a receipt: today's Advise path.
    Unknown mode fails closed (no LLM) so a typo cannot silently judge-and-call.
    """
    if not (url or "").strip() or mode == "off":
        return AdviseDecision(call_jev=False, call_llm=True, gate="off", receipt=None)
    active = _active_mode(mode)
    if active is None:
        return AdviseDecision(
            call_jev=False,
            call_llm=False,
            gate="jev_error",
            receipt=_receipt(
                mode="gate",
                latency_ms=0,
                answers=None,
                gate="jev_error",
                llm_invoked=False,
            ),
        )
    if question_pack != PACK_ID:
        return _fail_closed(active, 0)
    if pack is None or is_thin_evidence(pack):
        return AdviseDecision(
            call_jev=False,
            call_llm=False,
            gate="thin_evidence",
            receipt=_receipt(
                mode=active,
                latency_ms=0,
                answers=None,
                gate="thin_evidence",
                llm_invoked=False,
            ),
        )
    return None


def decide_advise(
    *,
    mode: str,
    min_confidence: float,
    judgment: SystemOneJudgment,
) -> AdviseDecision:
    """Policy after a System One attempt. Does not invent answers on error."""
    active = _active_mode(mode) or "gate"
    if judgment.error or not judgment.answers:
        return _fail_closed(active, judgment.latency_ms)
    if judgment_abstains(judgment.answers, min_confidence):
        call_llm = active == "shadow"
        return AdviseDecision(
            call_jev=True,
            call_llm=call_llm,
            gate="abstain",
            receipt=_receipt(
                mode=active,
                latency_ms=judgment.latency_ms,
                answers=judgment.answers,
                gate="abstain",
                llm_invoked=call_llm,
            ),
        )
    return AdviseDecision(
        call_jev=True,
        call_llm=True,
        gate="pass",
        receipt=_receipt(
            mode=active,
            latency_ms=judgment.latency_ms,
            answers=judgment.answers,
            gate="pass",
            llm_invoked=True,
        ),
    )
