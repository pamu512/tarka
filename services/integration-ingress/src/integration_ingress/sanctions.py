from __future__ import annotations

"""Sanctions & PEP screening against the OpenSanctions consolidated dataset.

Downloads the FtM entities JSON-lines file, caches it locally, and provides
fuzzy name matching with optional country / date-of-birth filters.

**Boundary vs decision-api:** This module is the **integration-plane bulk screener**
(offline FtM cache + Levenshtein). Real-time vendor enrichment for rules uses
``decision_api.vendors.plugins.opensanctions`` (OpenSanctions Match API →
``NormalizedVendorSignal``). Do not merge the two paths without an explicit
shared adapter; they serve different latency and audit contracts.

**Persistence (SR-16):** Every adapter invocation inserts a row into
``sanctions_screening_logs`` (Postgres) before returning. If persistence fails,
the request fails with **503 SCREENING_PERSISTENCE_FAILED** (no ephemeral-only
screening). After a successful insert, a fail-soft JSONL mirror is appended
(``SANCTIONS_SCREENING_JOURNAL_PATH``). The on-disk FtM cache is the dataset
artifact; in-process ``_entities`` is a rebuildable search index, not the
audit record of record.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from integration_ingress.db import SessionLocal
from integration_ingress.models import SanctionsScreeningLog

log = logging.getLogger(__name__)

_DATASET_URL = "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
_CACHE_DIR = Path(os.environ.get("SANCTIONS_CACHE_DIR", "/tmp/sanctions_cache"))
_CACHE_FILE = _CACHE_DIR / "entities.ftm.json"
_CACHE_TTL_SECONDS = int(os.environ.get("SANCTIONS_CACHE_TTL", str(24 * 3600)))
_DOWNLOAD_TIMEOUT = int(os.environ.get("SANCTIONS_DOWNLOAD_TIMEOUT", "300"))
_SCREENING_JOURNAL_SCHEMA = "tarka.sanctions_screening_journal/v1"

_MAX_MATCH_ROWS_IN_LOG = 10
_MAX_ENTITY_NAME_LEN = 512
_MAX_TENANT_ID_LEN = 128
_LIST_INGEST_SOURCE = "opensanctions"
_SYNTHETIC_SUBJECT_PREFIX = "ops:"


def screening_journal_path() -> Path:
    override = os.environ.get("SANCTIONS_SCREENING_JOURNAL_PATH", "").strip()
    if override:
        return Path(override)
    return _CACHE_DIR / "sanctions_screening_journal.jsonl"


def append_screening_journal(record: dict[str, Any]) -> None:
    """Fail-soft JSONL mirror after Postgres commit (SR-16)."""
    path = screening_journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        log.debug("sanctions_screening_journal_append_failed", exc_info=True)


def read_screening_journal(*, limit: int = 50) -> list[dict[str, Any]]:
    """Tail recent journal rows (newest last in file → returned newest-first)."""
    lim = max(1, min(int(limit or 50), 500))
    path = screening_journal_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
        if len(out) >= lim:
            break
    return out


def refresh_stamp_path() -> Path:
    override = os.environ.get("SANCTIONS_REFRESH_STAMP_PATH", "").strip()
    if override:
        return Path(override)
    return _CACHE_DIR / "sanctions_refresh_stamp.json"


def load_refresh_stamp() -> dict[str, Any]:
    path = refresh_stamp_path()
    if not path.is_file():
        return {
            "last_refresh_at": None,
            "last_refresh_by": None,
            "force_download": None,
            "refresh_count": 0,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "last_refresh_at": None,
            "last_refresh_by": None,
            "force_download": None,
            "refresh_count": 0,
        }
    if not isinstance(data, dict):
        return {
            "last_refresh_at": None,
            "last_refresh_by": None,
            "force_download": None,
            "refresh_count": 0,
        }
    return {
        "last_refresh_at": data.get("last_refresh_at"),
        "last_refresh_by": data.get("last_refresh_by"),
        "force_download": data.get("force_download"),
        "refresh_count": int(data.get("refresh_count") or 0),
    }


def record_refresh_stamp(*, actor: str, force_download: bool) -> dict[str, Any]:
    prev = load_refresh_stamp()
    stamp = {
        "schema_id": "tarka.sanctions_refresh_stamp/v1",
        "last_refresh_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "last_refresh_by": (actor or "operator").strip()[:128] or "operator",
        "force_download": bool(force_download),
        "refresh_count": int(prev.get("refresh_count") or 0) + 1,
    }
    path = refresh_stamp_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        log.debug("sanctions_refresh_stamp_write_failed", exc_info=True)
    return stamp


def schedule_posture() -> dict[str, Any]:
    """Cron/schedule honesty — Motiva-class continuous needs an operator schedule."""
    expr = os.environ.get("TARKA_SANCTIONS_REFRESH_SCHEDULE", "").strip()
    return {
        "configured": bool(expr),
        "expression": expr or None,
        "env": "TARKA_SANCTIONS_REFRESH_SCHEDULE",
        "note": (
            "Set a cron/k8s CronJob that POSTs /v1/ops/sanctions-screening-refresh "
            "(example: infra/deploy/examples/sanctions-refresh-cronjob.yaml). "
            "Unset schedule ≠ Marble Motiva continuous lists."
        ),
        "cronjob_example": "infra/deploy/examples/sanctions-refresh-cronjob.yaml",
    }


async def _persist_screening_log(
    tenant_id: str,
    entity_name: str,
    match_found: bool,
    match_details: dict[str, Any],
) -> uuid.UUID:
    """Insert screening log; raises HTTPException 503 on persistence failure."""
    tid = (tenant_id or "").strip()[:_MAX_TENANT_ID_LEN] or "(unknown_tenant)"
    ename = (entity_name or "").strip()[:_MAX_ENTITY_NAME_LEN] or "(missing)"

    async with SessionLocal() as session:
        log_row = SanctionsScreeningLog(
            tenant_id=tid,
            entity_name=ename,
            match_found=match_found,
            match_details=match_details,
        )
        session.add(log_row)
        try:
            await session.commit()
            await session.refresh(log_row)
        except SQLAlchemyError as e:
            await session.rollback()
            log.warning("sanctions_screening_logs insert failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail={
                    "reason_code": "SCREENING_PERSISTENCE_FAILED",
                    "message": "Could not persist sanctions screening log.",
                },
            ) from e
    log_id = log_row.id
    details = match_details if isinstance(match_details, dict) else {}
    append_screening_journal(
        {
            "schema_id": _SCREENING_JOURNAL_SCHEMA,
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "screening_log_id": str(log_id),
            "tenant_id": tid,
            "entity_name": ename,
            "match_found": bool(match_found),
            "match_count": int(details.get("match_count") or 0),
            "subject_id": details.get("subject_id"),
            "list_id": _list_id_from_match_details(details) or None,
        }
    )
    return log_id


def _list_id_from_match_details(match_details: dict[str, Any] | None) -> str:
    if not isinstance(match_details, dict):
        return ""
    raw = str(match_details.get("list_id") or "").strip()
    if raw:
        return raw[:128]
    matches = match_details.get("matches")
    if isinstance(matches, list) and matches and isinstance(matches[0], dict):
        return str(matches[0].get("id") or "").strip()[:128]
    return ""


def plan_list_hit_ingest(*, tenant_id: str, subject_id: str, list_id: str) -> dict[str, Any] | None:
    """Map a persisted list hit onto the same Person evaluate uses. No fuzzy join."""
    tid = (tenant_id or "").strip()
    person = (subject_id or "").strip()
    lid = (list_id or "").strip()
    if not tid or not person or not lid:
        return None
    if person.startswith(_SYNTHETIC_SUBJECT_PREFIX):
        return None
    object_id = lid if lid.startswith("list:") else f"list:{lid[:128]}"
    return {
        "tenant_id": tid,
        "source": _LIST_INGEST_SOURCE,
        "mapping": {
            "join_field": "entity_id",
            "object_field": "list_id",
            "object_type": "List",
            "relationship": "HAS_LIST",
        },
        "record": {"entity_id": person, "list_id": object_id},
    }


async def maybe_ingest_list_hit(
    http: httpx.AsyncClient | None,
    *,
    tenant_id: str,
    subject_id: str,
    list_id: str,
) -> dict[str, Any]:
    """POST /v1/ingest/objects. Empty GRAPH_SERVICE_URL or graph miss is fail-soft."""
    body = plan_list_hit_ingest(tenant_id=tenant_id, subject_id=subject_id, list_id=list_id)
    if body is None:
        return {"status": "skipped"}
    base = os.environ.get("GRAPH_SERVICE_URL", "").strip()
    if not base:
        return {"status": "graph:unconfigured"}
    url = f"{base.rstrip('/')}/v1/ingest/objects"
    own = http is None
    client = http or httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    try:
        r = await client.post(url, json=body)
        if r.status_code >= 400:
            log.warning("list ingest failed status=%s body=%s", r.status_code, r.text[:200])
            return {"status": "graph:write_failed", "http_status": r.status_code}
        return {"status": "ok"}
    except Exception:
        log.debug("list ingest failed", exc_info=True)
        return {"status": "graph:write_failed"}
    finally:
        if own:
            await client.aclose()


async def replay_journal_list_hits(http: httpx.AsyncClient | None) -> dict[str, Any]:
    """Refresh path: replay journaled hits onto AGE. Evaluate is not in this pipe."""
    ingested = 0
    skipped = 0
    failed = 0
    seen: set[tuple[str, str, str]] = set()
    for row in read_screening_journal(limit=500):
        if not isinstance(row, dict) or not row.get("match_found"):
            skipped += 1
            continue
        tid = str(row.get("tenant_id") or "").strip()
        sid = str(row.get("subject_id") or "").strip()
        lid = _list_id_from_match_details(row)
        key = (tid, sid, lid)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        if plan_list_hit_ingest(tenant_id=tid, subject_id=sid, list_id=lid) is None:
            skipped += 1
            continue
        out = await maybe_ingest_list_hit(http, tenant_id=tid, subject_id=sid, list_id=lid)
        status = str(out.get("status") or "")
        if status == "ok":
            ingested += 1
        elif status in {"graph:unconfigured", "skipped"}:
            skipped += 1
        else:
            failed += 1
    return {"ingested": ingested, "skipped": skipped, "failed": failed}


def _levenshtein(s: str, t: str) -> int:
    n, m = len(s), len(t)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        curr[0] = i
        for j in range(1, m + 1):
            cost = 0 if s[i - 1] == t[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[m]


def _similarity(a: str, b: str) -> float:
    a_low, b_low = a.lower().strip(), b.lower().strip()
    if not a_low or not b_low:
        return 0.0
    dist = _levenshtein(a_low, b_low)
    max_len = max(len(a_low), len(b_low))
    return 1.0 - dist / max_len


class SanctionsScreener:
    """Downloads the OpenSanctions consolidated dataset and performs
    in-memory fuzzy name matching for sanctions / PEP screening."""

    def __init__(
        self,
        dataset_url: str = _DATASET_URL,
        cache_dir: Path = _CACHE_DIR,
        cache_ttl: int = _CACHE_TTL_SECONDS,
        score_threshold: float = 0.80,
    ) -> None:
        self.dataset_url = dataset_url
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / "entities.ftm.json"
        self.cache_ttl = cache_ttl
        self.score_threshold = score_threshold
        self._entities: list[dict[str, Any]] = []
        self._loaded = False
        self._load_lock = asyncio.Lock()

    def _cache_is_fresh(self) -> bool:
        if not self.cache_file.exists():
            return False
        age = time.time() - self.cache_file.stat().st_mtime
        return age < self.cache_ttl

    async def _download(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        log.info("downloading OpenSanctions dataset from %s", self.dataset_url)
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
                async with client.stream("GET", self.dataset_url) as resp:
                    resp.raise_for_status()
                    tmp = self.cache_file.with_suffix(".tmp")
                    with open(tmp, "wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            fh.write(chunk)
                    tmp.rename(self.cache_file)
            log.info("dataset saved to %s", self.cache_file)
        except Exception as exc:
            log.error("failed to download sanctions dataset: %s", exc)
            if self.cache_file.exists():
                log.warning("using stale cache")
            else:
                raise

    def _parse_entities_sync(self) -> list[dict[str, Any]]:
        """CPU-bound parse — runs in a thread pool."""
        entities: list[dict[str, Any]] = []
        relevant_schemas = {"Person", "LegalEntity", "Company", "Organization"}
        with open(self.cache_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                schema = obj.get("schema", "")
                if schema not in relevant_schemas:
                    continue
                props = obj.get("properties", {})
                names: list[str] = props.get("name", []) + props.get("alias", [])
                if not names:
                    continue
                entities.append(
                    {
                        "id": obj.get("id", ""),
                        "schema": schema,
                        "names": [n.lower().strip() for n in names],
                        "countries": [
                            c.lower()
                            for c in props.get("country", []) + props.get("nationality", [])
                        ],
                        "dobs": props.get("birthDate", []),
                        "topics": obj.get("datasets", []),
                        "caption": obj.get("caption", names[0] if names else ""),
                    }
                )
        return entities

    async def load(self, *, force_download: bool = False) -> None:
        async with self._load_lock:
            if self._loaded and not force_download:
                return
            if force_download or not self._cache_is_fresh():
                await self._download()
            self._entities = await asyncio.to_thread(self._parse_entities_sync)
            self._loaded = True
            log.info("loaded %d sanctioned entities into memory", len(self._entities))

    def dataset_cache_meta(self) -> dict[str, Any]:
        """Explain helpers: cache path, mtime, age (seconds)."""
        path = self.cache_file
        meta: dict[str, Any] = {
            "dataset_cache_path": str(path),
            "score_threshold": self.score_threshold,
            "cache_ttl_seconds": self.cache_ttl,
        }
        try:
            if path.is_file():
                mtime = path.stat().st_mtime
                meta["dataset_cache_mtime_unix"] = mtime
                meta["dataset_cache_age_seconds"] = max(0.0, time.time() - mtime)
            else:
                meta["dataset_cache_mtime_unix"] = None
                meta["dataset_cache_age_seconds"] = None
        except OSError:
            meta["dataset_cache_mtime_unix"] = None
            meta["dataset_cache_age_seconds"] = None
        return meta

    def screening_ops_posture(self) -> dict[str, Any]:
        """Ops posture for continuous bulk FtM cache vs realtime Match API (Marble gap)."""
        meta = self.dataset_cache_meta()
        age = meta.get("dataset_cache_age_seconds")
        cache_present = meta.get("dataset_cache_mtime_unix") is not None
        cache_fresh = bool(cache_present and age is not None and float(age) < float(self.cache_ttl))
        entity_count = len(self._entities) if self._loaded else 0
        if cache_fresh and self._loaded and entity_count > 0:
            continuous_status = "ready"
        elif cache_present and not cache_fresh:
            continuous_status = "stale_cache"
        elif cache_present and not self._loaded:
            continuous_status = "cache_on_disk_not_loaded"
        else:
            continuous_status = "not_loaded"
        journal_lines = 0
        try:
            jp = screening_journal_path()
            if jp.is_file():
                with jp.open("r", encoding="utf-8") as fh:
                    for i, _ in enumerate(fh, start=1):
                        journal_lines = i
                        if i >= 10_000:
                            break
        except OSError:
            journal_lines = 0
        stamp = load_refresh_stamp()
        schedule = schedule_posture()
        cache_ready = continuous_status == "ready"
        # Cache ready ≠ Motiva-class continuous; ops need a refresh schedule + stamp.
        continuous_ops_ready = bool(
            cache_ready and schedule["configured"] and stamp.get("last_refresh_at")
        )
        blockers: list[str] = []
        if not cache_ready:
            blockers.append(f"cache_{continuous_status}")
        if not schedule["configured"]:
            blockers.append("refresh_schedule_unset")
        if not stamp.get("last_refresh_at"):
            blockers.append("no_refresh_stamp")
        return {
            "schema_id": "tarka.sanctions_screening_ops_posture/v1",
            "continuous_bulk": {
                "status": continuous_status,
                "dataset_url": self.dataset_url,
                "entities_loaded": entity_count,
                "index_loaded": self._loaded,
                "cache_present": cache_present,
                "cache_fresh": cache_fresh,
                "screening_journal_lines": journal_lines,
                "refresh": "POST /v1/ops/sanctions-screening-refresh",
                "journal": "GET /v1/ops/sanctions-screening-journal",
                "last_refresh_at": stamp.get("last_refresh_at"),
                "last_refresh_by": stamp.get("last_refresh_by"),
                "refresh_count": stamp.get("refresh_count") or 0,
                **meta,
            },
            "schedule": schedule,
            "realtime_match_api": {
                "plugin": "opensanctions",
                "plane": "decision_api.vendors.plugins.opensanctions",
                "note": (
                    "Evaluate-time Match API via vendor plugin — separate from this "
                    "ingress FtM bulk screener. Configure TARKA_VENDOR_OPENSANCTIONS_API_KEY."
                ),
            },
            "vs_marble": (
                "Bulk FtM cache + journaled screens ≠ Marble Motiva+ES continuous list "
                "product. continuous_ops_ready requires fresh cache + configured refresh "
                "schedule + at least one admin refresh stamp."
            ),
            "ready_for_continuous_claim": cache_ready,
            "continuous_ops_ready": continuous_ops_ready,
            "continuous_ops_blockers": blockers,
            "motiva_claim_allowed": False,
            "screen_persist": "POST /v1/ops/sanctions-screen",
            "honesty": (
                "Persistence-required screening (SR-16). Empty/missing cache is not a pass. "
                "Do not claim Motiva-class continuous lists from cache alone. "
                "motiva_claim_allowed stays false."
            ),
        }

    async def screen(
        self,
        name: str,
        country: str | None = None,
        dob: str | None = None,
    ) -> list[dict[str, Any]]:
        """Screen a name against the sanctions list (explained fuzzy hits)."""
        await self.load()
        name_lower = name.lower().strip()
        if not name_lower:
            return []

        hits: list[dict[str, Any]] = []
        for ent in self._entities:
            best_name = ""
            best_raw = 0.0
            for n in ent["names"]:
                s = _similarity(name_lower, n)
                if s > best_raw:
                    best_raw = s
                    best_name = n
            if best_raw < self.score_threshold:
                continue

            score = best_raw
            dampens: list[str] = []
            if country:
                c_low = country.lower().strip()
                if ent["countries"] and c_low not in ent["countries"]:
                    score *= 0.8
                    dampens.append("country_mismatch_x0.8")

            if dob and ent["dobs"] and not any(dob in d for d in ent["dobs"]):
                score *= 0.9
                dampens.append("dob_mismatch_x0.9")

            if score >= self.score_threshold:
                hits.append(
                    {
                        "id": ent["id"],
                        "caption": ent["caption"],
                        "schema": ent["schema"],
                        "matched_name": best_name,
                        "score_raw": round(best_raw, 4),
                        "score": round(score, 4),
                        "score_threshold": self.score_threshold,
                        "score_dampens": dampens,
                        "countries": ent["countries"],
                        "dobs": ent["dobs"],
                        "topics": ent["topics"],
                    }
                )

        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits


_default_screener: SanctionsScreener | None = None


def _get_screener() -> SanctionsScreener:
    global _default_screener
    if _default_screener is None:
        _default_screener = SanctionsScreener()
    return _default_screener


async def verify_sanctions(
    tenant_id: str,
    subject_id: str,
    raw: dict[str, Any] | None,
) -> dict[str, Any]:
    """Adapter-compatible function for the ADAPTERS registry.

    Expected ``raw`` keys: ``name`` (required), ``country``, ``dob``.
    """
    raw = raw or {}
    name = raw.get("name", "")

    if not name:
        log_id = await _persist_screening_log(
            tenant_id,
            "(missing)",
            False,
            {
                "adapter": "sanctions",
                "subject_id": subject_id,
                "validation": "missing_name",
                "error": "missing 'name' in request payload",
            },
        )
        return {
            "status": "error",
            "adapter": "sanctions",
            "subject_id": subject_id,
            "document_type": None,
            "liveness": None,
            "pep_sanctions_match": None,
            "confidence": None,
            "raw_reference": None,
            "details": {
                "error": "missing 'name' in request payload",
                "screening_log_id": str(log_id),
            },
        }

    screener = _get_screener()
    matches = await screener.screen(
        name=name,
        country=raw.get("country"),
        dob=raw.get("dob"),
    )
    has_match = len(matches) > 0
    top_score = matches[0]["score"] if matches else 0.0

    cache_meta = screener.dataset_cache_meta()
    match_details: dict[str, Any] = {
        "adapter": "sanctions",
        "subject_id": subject_id,
        "query_name": name,
        "query_country": raw.get("country"),
        "query_dob": raw.get("dob"),
        "match_count": len(matches),
        "matches": matches[:_MAX_MATCH_ROWS_IN_LOG],
        **cache_meta,
        "index_scope": "process_memory_rebuilt_from_disk_cache",
        "explain_schema": "tarka.sanctions_match_explain/v1",
    }

    log_id = await _persist_screening_log(
        tenant_id,
        str(name),
        has_match,
        match_details,
    )

    ingest_out: dict[str, Any] = {"status": "skipped"}
    if has_match:
        lid = str((matches[0] or {}).get("id") or "").strip() if matches else ""
        ingest_out = await maybe_ingest_list_hit(
            None,
            tenant_id=tenant_id,
            subject_id=subject_id,
            list_id=lid,
        )

    return {
        "status": "verified",
        "adapter": "sanctions",
        "subject_id": subject_id,
        "document_type": None,
        "liveness": None,
        "pep_sanctions_match": has_match,
        "confidence": round(top_score, 4) if has_match else 1.0,
        "raw_reference": matches[0]["id"] if matches else None,
        "details": {
            "tenant_id": tenant_id,
            "query_name": name,
            "query_country": raw.get("country"),
            "query_dob": raw.get("dob"),
            "match_count": len(matches),
            "matches": matches[:10],
            "screening_log_id": str(log_id),
            "screening_journal_path": str(screening_journal_path()),
            "graph_ingest": ingest_out,
            **cache_meta,
            "index_scope": "process_memory_rebuilt_from_disk_cache",
            "explain_schema": "tarka.sanctions_match_explain/v1",
        },
    }
