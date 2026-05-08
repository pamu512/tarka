"""Redis-coordinated batch assembly and Merkle batch-root computation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import redis.asyncio as redis

from ingestor.merkle import merkle_root_sha256
from ingestor.settings import IngestorSettings

logger = logging.getLogger(__name__)

# Append manifest fingerprint to the list; if the batch threshold is reached,
# atomically drain BATCH_SIZE elements for anchoring and leave overflow on the list.
_BATCH_APPEND_LUA = """
local batch_size = tonumber(ARGV[2])
redis.call('RPUSH', KEYS[1], ARGV[1])
local len = redis.call('LLEN', KEYS[1])
if len >= batch_size then
  local elems = redis.call('LRANGE', KEYS[1], 0, batch_size - 1)
  redis.call('LTRIM', KEYS[1], batch_size, -1)
  local out = {'batch'}
  for i = 1, #elems do
    out[#out + 1] = elems[i]
  end
  return out
end
return {'noop'}
"""


def _parse_record(token: str) -> tuple[uuid.UUID, bytes]:
    parts = token.split("|", 1)
    if len(parts) != 2:
        raise ValueError("invalid batch record")
    uid = uuid.UUID(hex=parts[0])
    digest = bytes.fromhex(parts[1])
    if len(digest) != 32:
        raise ValueError("invalid leaf digest")
    return uid, digest


async def append_manifest_and_maybe_finalize(
    redis_client: redis.Redis,
    settings: IngestorSettings,
    *,
    tenant_id: str,
    manifest_id: uuid.UUID,
    raw_sha256: bytes,
) -> dict[str, Any] | None:
    """Return anchor payload dict when a batch is sealed; otherwise None."""
    if len(raw_sha256) != 32:
        raise ValueError("raw_sha256 must be 32 bytes")
    tid = tenant_id.strip()
    if not tid:
        raise ValueError("tenant_id must be non-empty")
    batch_list_key = f"{settings.redis_batch_list_key}:{tid}"
    batch_seq_key = f"{settings.redis_batch_seq_key}:{tid}"
    record = f"{manifest_id.hex}|{raw_sha256.hex()}"
    raw = await redis_client.eval(
        _BATCH_APPEND_LUA,
        1,
        batch_list_key,
        record,
        str(settings.batch_size),
    )
    if not raw:
        logger.error(
            "redis batch script returned empty payload",
            extra={"redis_key": batch_list_key},
        )
        raise RuntimeError("redis batch script returned empty payload")

    parts = list(raw)

    def _token_text(token: object) -> str:
        if isinstance(token, (bytes, bytearray)):
            return token.decode()
        return str(token)

    flag = _token_text(parts[0])
    if flag == "noop":
        return None
    if flag != "batch":
        logger.error("unexpected redis batch status", extra={"status": flag})
        raise RuntimeError("unexpected redis batch status")

    tokens = [p.decode() if isinstance(p, (bytes, bytearray)) else str(p) for p in parts[1:]]
    if len(tokens) != settings.batch_size:
        logger.error(
            "batch slice size mismatch",
            extra={"expected": settings.batch_size, "got": len(tokens)},
        )
        raise RuntimeError("batch slice size mismatch")

    first_uuid, first_leaf = _parse_record(tokens[0])
    last_uuid, last_leaf = _parse_record(tokens[-1])
    leaves = [_parse_record(t)[1] for t in tokens]
    root = merkle_root_sha256(leaves)
    batch_seq = int(await redis_client.incr(batch_seq_key))

    return {
        "batch_seq": batch_seq,
        "batch_root_hex": root.hex(),
        "manifest_count": settings.batch_size,
        "first_manifest_id": first_uuid,
        "last_manifest_id": last_uuid,
        "first_leaf_sha256_hex": first_leaf.hex(),
        "last_leaf_sha256_hex": last_leaf.hex(),
    }
