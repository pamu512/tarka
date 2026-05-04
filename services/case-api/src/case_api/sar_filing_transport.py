"""FinCEN BSA E-Filing transport: configuration checks, validation, and SFTP payload (SR-08, SR-10)."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from case_api.models import SARFiling, SarFiling

log = logging.getLogger(__name__)

_MANDATORY_FILING_KEYS = ("filer_tin", "financial_institution_name")


def build_sftp_destination() -> str | None:
    return os.environ.get("FINCEN_BSA_SFTP_HOST", "").strip() or None


def build_sar_transmission_package(intent: "SarFiling", artifact: "SARFiling") -> tuple[str, bytes]:
    """Build the exact on-the-wire artifact FinCEN BSA batch (XML) or structured JSON for non-XML formats.

    Returns ``(remote_filename, body_bytes)`` for SFTP placement.
    """
    from case_api.models import SARFiling as _SARFiling

    if not isinstance(artifact, _SARFiling):
        raise TypeError("artifact must be SARFiling")

    rid = str(artifact.report_data.get("report_id") or artifact.id)[:64]
    if (artifact.format or "").strip() == "fincen_xml" and (artifact.xml_content or "").strip():
        name = f"EFILING_BATCH_{artifact.id.hex[:16]}_{intent.id.hex[:8]}.xml"
        return name, artifact.xml_content.strip().encode("utf-8")

    payload = {
        "EFilingBatchJSON": {
            "version": "1.0",
            "intent_id": str(intent.id),
            "artifact_id": str(artifact.id),
            "format": artifact.format,
            "report_data": artifact.report_data,
            "narrative_excerpt": (artifact.narrative or "")[:4000],
        }
    }
    name = f"EFILING_BATCH_{artifact.id.hex[:16]}_{intent.id.hex[:8]}.json"
    return name, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


def upload_sar_bytes(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_dir: str,
    filename: str,
    body: bytes,
) -> None:
    """Blocking SFTP upload (invoke via ``asyncio.to_thread`` from async workers)."""
    import paramiko

    transport = paramiko.Transport((host, int(port)))
    try:
        pw = password.strip() if password else None
        transport.connect(username=(username.strip() if username else None) or None, password=pw)
        sftp = paramiko.SFTPClient.from_transport(transport)
        if sftp is None:
            raise RuntimeError("paramiko SFTPClient unavailable")
        try:
            path = f"{remote_dir.rstrip('/')}/{filename}"
            with sftp.file(path, "wb") as fh:
                fh.write(body)
        finally:
            sftp.close()
    finally:
        transport.close()


def build_sar_filing_data(body: dict[str, Any], report: Any) -> dict[str, Any]:
    """Merge request overrides with generated report institution for mandatory-field checks."""
    override = body.get("filing_institution") if isinstance(body.get("filing_institution"), dict) else {}
    inst = {**(getattr(report, "institution", None) or {}), **override}
    filer_tin = inst.get("filer_tin") or inst.get("tin") or inst.get("ein")
    fin_name = inst.get("financial_institution_name") or inst.get("name")
    return {
        "filer_tin": filer_tin,
        "financial_institution_name": fin_name,
        "report_id": getattr(report, "report_id", None),
        "format": getattr(report, "format", None),
    }


def validate_pre_filing(filing_data: dict[str, Any]) -> list[str]:
    """Return blocking validation errors for mandatory filing_data fields (empty list == OK)."""
    errors: list[str] = []
    for key in _MANDATORY_FILING_KEYS:
        val = filing_data.get(key)
        if val is None:
            errors.append(f"missing_field:{key}")
            continue
        if isinstance(val, str) and not val.strip():
            errors.append(f"empty_field:{key}")
    return errors
