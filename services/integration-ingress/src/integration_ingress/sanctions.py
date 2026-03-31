"""Sanctions & PEP screening against the OpenSanctions consolidated dataset.

Downloads the FtM entities JSON-lines file, caches it locally, and provides
fuzzy name matching with optional country / date-of-birth filters.

All I/O is async-safe — network downloads use httpx and file parsing is
offloaded to a thread pool to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

_DATASET_URL = (
    "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
)
_CACHE_DIR = Path(os.environ.get("SANCTIONS_CACHE_DIR", "/tmp/sanctions_cache"))
_CACHE_FILE = _CACHE_DIR / "entities.ftm.json"
_CACHE_TTL_SECONDS = int(os.environ.get("SANCTIONS_CACHE_TTL", str(24 * 3600)))
_DOWNLOAD_TIMEOUT = int(os.environ.get("SANCTIONS_DOWNLOAD_TIMEOUT", "300"))


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
                            for c in props.get("country", [])
                            + props.get("nationality", [])
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

    async def screen(
        self,
        name: str,
        country: str | None = None,
        dob: str | None = None,
    ) -> list[dict[str, Any]]:
        """Screen a name against the sanctions list."""
        await self.load()
        name_lower = name.lower().strip()
        if not name_lower:
            return []

        hits: list[dict[str, Any]] = []
        for ent in self._entities:
            best_score = max(
                (_similarity(name_lower, n) for n in ent["names"]),
                default=0.0,
            )
            if best_score < self.score_threshold:
                continue

            if country:
                c_low = country.lower().strip()
                if ent["countries"] and c_low not in ent["countries"]:
                    best_score *= 0.8

            if dob:
                if ent["dobs"] and not any(dob in d for d in ent["dobs"]):
                    best_score *= 0.9

            if best_score >= self.score_threshold:
                hits.append(
                    {
                        "id": ent["id"],
                        "caption": ent["caption"],
                        "schema": ent["schema"],
                        "score": round(best_score, 4),
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
        return {
            "status": "error",
            "adapter": "sanctions",
            "subject_id": subject_id,
            "document_type": None,
            "liveness": None,
            "pep_sanctions_match": None,
            "confidence": None,
            "raw_reference": None,
            "details": {"error": "missing 'name' in request payload"},
        }

    screener = _get_screener()
    matches = await screener.screen(
        name=name,
        country=raw.get("country"),
        dob=raw.get("dob"),
    )
    has_match = len(matches) > 0
    top_score = matches[0]["score"] if matches else 0.0

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
        },
    }
