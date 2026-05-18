from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.kms_adapter import KMSAdapter
from integration_ingress.models import IntegrationSecret


def _mask(value: str) -> str:
    """UI-safe hint: never show full secret; only bullets + last four characters."""
    if not value:
        return ""
    s = str(value)
    if len(s) <= 4:
        return "••••"
    return f"••••{s[-4:]}"


class InMemoryVault:
    def __init__(self, *, kms: KMSAdapter, active_key_id: str) -> None:
        self._kms = kms
        self.provider = kms.provider
        self.active_key_id = active_key_id
        self._dek_cache: dict[str, bytes] = {}
        self._encrypt_calls = 0
        self._decrypt_calls = 0

    @staticmethod
    def _xor(data: bytes, key: bytes) -> bytes:
        out = bytearray(len(data))
        for i, b in enumerate(data):
            out[i] = b ^ key[i % len(key)]
        return bytes(out)

    def _encrypt(self, config: dict[str, Any], *, key_id: str) -> tuple[str, str]:
        payload = json.dumps({str(k): str(v) for k, v in config.items()}, sort_keys=True).encode(
            "utf-8"
        )
        # Envelope style: generate a data key, wrap with KMS, encrypt payload locally.
        data_key = hashlib.sha256(os.urandom(32)).digest()
        self._encrypt_calls += 1
        wrapped = self._kms.encrypt(data_key, key_id=key_id)
        ciphertext = self._xor(payload, data_key)
        return (
            base64.urlsafe_b64encode(ciphertext).decode("utf-8"),
            base64.urlsafe_b64encode(wrapped).decode("utf-8"),
        )

    def _decrypt(
        self, ciphertext: str, *, key_id: str, wrapped_key: str | None = None
    ) -> dict[str, str]:
        try:
            raw_cipher = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
            if wrapped_key:
                dek_cache_key = hashlib.sha256(wrapped_key.encode("utf-8")).hexdigest()
                data_key = self._dek_cache.get(dek_cache_key)
                if data_key is None:
                    raw_wrapped = base64.urlsafe_b64decode(wrapped_key.encode("utf-8"))
                    self._decrypt_calls += 1
                    data_key = self._kms.decrypt(raw_wrapped, key_id=key_id)
                    self._dek_cache[dek_cache_key] = data_key
                data = self._xor(raw_cipher, data_key)
            else:
                # Backward compatibility with older directly KMS-encrypted payloads.
                self._decrypt_calls += 1
                data = self._kms.decrypt(raw_cipher, key_id=key_id)
            parsed = json.loads(data.decode("utf-8"))
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except Exception:
            return {}
        return {}

    async def set_config(
        self, session: AsyncSession, tenant_id: str, provider_id: str, config: dict[str, Any]
    ) -> None:
        filtered = {str(k): str(v) for k, v in (config or {}).items() if str(v).strip()}
        encrypted, wrapped = self._encrypt(filtered, key_id=self.active_key_id)
        result = await session.execute(
            select(IntegrationSecret).where(
                IntegrationSecret.tenant_id == tenant_id,
                IntegrationSecret.provider_id == provider_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.ciphertext = encrypted
            row.wrapped_key = wrapped
            row.key_id = self.active_key_id
        else:
            session.add(
                IntegrationSecret(
                    tenant_id=tenant_id,
                    provider_id=provider_id,
                    key_id=self.active_key_id,
                    wrapped_key=wrapped,
                    ciphertext=encrypted,
                )
            )

    async def get_config(
        self, session: AsyncSession, tenant_id: str, provider_id: str
    ) -> dict[str, str]:
        result = await session.execute(
            select(IntegrationSecret).where(
                IntegrationSecret.tenant_id == tenant_id,
                IntegrationSecret.provider_id == provider_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return {}
        return self._decrypt(
            row.ciphertext,
            key_id=row.key_id or self.active_key_id,
            wrapped_key=row.wrapped_key,
        )

    async def get_masked_config(
        self, session: AsyncSession, tenant_id: str, provider_id: str
    ) -> dict[str, str]:
        plain = await self.get_config(session, tenant_id, provider_id)
        return {k: _mask(v) for k, v in plain.items()}

    def set_active_key(self, key_id: str, material: str) -> None:
        self.active_key_id = key_id
        self._kms.set_key_material(key_id, material)

    async def rotate_all_secrets(
        self, session: AsyncSession, new_key_id: str, new_key_material: str
    ) -> int:
        self.set_active_key(new_key_id, new_key_material)
        result = await session.execute(select(IntegrationSecret))
        rows = result.scalars().all()
        rotated = 0
        for row in rows:
            plain = self._decrypt(
                row.ciphertext, key_id=row.key_id or new_key_id, wrapped_key=row.wrapped_key
            )
            row.ciphertext, row.wrapped_key = self._encrypt(plain, key_id=new_key_id)
            row.key_id = new_key_id
            rotated += 1
        return rotated

    async def rotate_secrets_batch(
        self,
        session: AsyncSession,
        *,
        new_key_id: str,
        new_key_material: str,
        batch_size: int = 100,
        offset: int = 0,
    ) -> tuple[int, int, int]:
        self.set_active_key(new_key_id, new_key_material)
        total = int(
            (
                await session.execute(select(func.count()).select_from(IntegrationSecret))
            ).scalar_one()
        )
        result = await session.execute(
            select(IntegrationSecret)
            .order_by(IntegrationSecret.created_at.asc())
            .offset(offset)
            .limit(batch_size)
        )
        rows = result.scalars().all()
        processed = len(rows)
        rotated = 0
        for row in rows:
            plain = self._decrypt(
                row.ciphertext, key_id=row.key_id or new_key_id, wrapped_key=row.wrapped_key
            )
            row.ciphertext, row.wrapped_key = self._encrypt(plain, key_id=new_key_id)
            row.key_id = new_key_id
            rotated += 1
        return processed, rotated, total

    def metrics(self) -> dict[str, int]:
        return {
            "encrypt_calls": self._encrypt_calls,
            "decrypt_calls": self._decrypt_calls,
            "dek_cache_entries": len(self._dek_cache),
        }
