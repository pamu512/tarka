"""Jev System One confidence gate for desk Advise.

Pattern only: fixed evidence pack, one ``POST /v1/systemone`` call, code policy.
Does not import ``@ax-llm/ax``. Never emits ALLOW, DENY, or Promote.
"""

from jev_system_one.client import SystemOneClient, SystemOneJudgment
from jev_system_one.pack import MISSING, build_evidence_pack, is_thin_evidence
from jev_system_one.policy import AdviseDecision, decide_advise, preflight_advise
from jev_system_one.questions import PACK_ID, build_systemone_request

__all__ = [
    "MISSING",
    "PACK_ID",
    "AdviseDecision",
    "SystemOneClient",
    "SystemOneJudgment",
    "build_evidence_pack",
    "build_systemone_request",
    "decide_advise",
    "is_thin_evidence",
    "preflight_advise",
]
