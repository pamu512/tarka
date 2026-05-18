#!/usr/bin/env python3
"""Create a persistent SQLite shadow DB with cross-case timeline demo rows (manual UI gate).

Usage (from ``tarka_v2_core/services/shadow_agent``)::

  pip install -e . -e ../ingestor -e ../shared
  export PYTHONPATH=src:../ingestor/src:../shared
  python scripts/seed_cross_case_timeline_demo.py ./shadow_timeline_demo.db

Start the shadow sidecar with::

  export SHADOW_DATABASE_URL=sqlite+aiosqlite:///$(pwd)/shadow_timeline_demo.db
  export SHADOW_API_KEY=dev-shadow-token-change-me
  uvicorn shadow_agent.main:app --host 127.0.0.1 --port 8801

Point Next.js at the sidecar (``SHADOW_AGENT_URL=http://127.0.0.1:8801``,
``SHADOW_API_KEY`` matching) and open decision detail for transaction id::

  11111111-1111-1111-1111-111111111111

You should see the orange cross-case node and the device alert for Case #123.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SERVICES / "shared", _SERVICES / "shadow_agent" / "src"):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import tarka_shared.audit_trail  # noqa: F401, E402
from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402
from tarka_shared.database.session import Base  # noqa: E402

CLEAN_TX = "11111111-1111-1111-1111-111111111111"
FRAUD_TX = "22222222-2222-2222-2222-222222222222"
SHARED_DEVICE = "device-gate-shared-01"


def _payload(*, tid: str, amount: float, fraud: bool, case_no: str, outcome: str) -> str:
    return json.dumps(
        {
            "transaction_id": tid,
            "amount": amount,
            "is_fraud": fraud,
            "device_id": SHARED_DEVICE,
            "ip_address": "198.51.100.10",
            "investigation_case_number": case_no,
            "case_outcome": outcome,
        },
        separators=(",", ":"),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("sqlite_path", type=Path, help="Path to SQLite file (created if missing)")
    args = p.parse_args()
    path = args.sqlite_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{path}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    fraud_ts = now - timedelta(days=90)
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.case_id.in_((FRAUD_TX, CLEAN_TX))))
        session.execute(delete(Case).where(Case.id.in_((FRAUD_TX, CLEAN_TX))))
        for cid, name in ((FRAUD_TX, "fraud-anchor"), (CLEAN_TX, "clean-anchor")):
            session.add(
                Case(
                    id=cid,
                    tenant_id=DEFAULT_TENANT_ID,
                    name=name,
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
        session.add(
            AuditLog(
                case_id=FRAUD_TX,
                action_taken=_payload(
                    tid=FRAUD_TX,
                    amount=999.0,
                    fraud=True,
                    case_no="123",
                    outcome="BLOCKED",
                ),
                code_executed=None,
                agent_notes=None,
                timestamp=fraud_ts,
            ),
        )
        session.add(
            AuditLog(
                case_id=CLEAN_TX,
                action_taken=_payload(
                    tid=CLEAN_TX,
                    amount=42.0,
                    fraud=False,
                    case_no="456",
                    outcome="CLEAN",
                ),
                code_executed=None,
                agent_notes=None,
                timestamp=now,
            ),
        )
        session.commit()
    print(f"Seeded cross-case demo into {path}")
    print(f"Open UI timeline for clean transaction UUID: {CLEAN_TX}")


if __name__ == "__main__":
    main()
