from __future__ import annotations

import hashlib
from typing import Protocol


class KMSAdapter(Protocol):
    provider: str

    def encrypt(self, plaintext: bytes, *, key_id: str) -> bytes: ...
    def decrypt(self, ciphertext: bytes, *, key_id: str) -> bytes: ...
    def set_key_material(self, key_id: str, material: str) -> None: ...


class LocalKMSAdapter:
    provider = "local"

    def __init__(self, keyring: dict[str, str]) -> None:
        self._keyring = {k: hashlib.sha256(v.encode("utf-8")).digest() for k, v in keyring.items()}

    def set_key_material(self, key_id: str, material: str) -> None:
        self._keyring[key_id] = hashlib.sha256(material.encode("utf-8")).digest()

    def _xor(self, data: bytes, key_id: str) -> bytes:
        key = self._keyring.get(key_id, next(iter(self._keyring.values())))
        out = bytearray(len(data))
        for i, b in enumerate(data):
            out[i] = b ^ key[i % len(key)]
        return bytes(out)

    def encrypt(self, plaintext: bytes, *, key_id: str) -> bytes:
        return self._xor(plaintext, key_id)

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> bytes:
        return self._xor(ciphertext, key_id)


class AwsKMSAdapter:
    provider = "aws"

    def __init__(self, *, region_name: str, endpoint_url: str = "") -> None:
        try:
            import boto3  # type: ignore
        except Exception as exc:
            raise RuntimeError("AWS KMS adapter requires boto3 installed") from exc
        kwargs = {"region_name": region_name}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        self._client = boto3.client("kms", **kwargs)

    def set_key_material(self, key_id: str, material: str) -> None:
        # Cloud KMS keys are externally managed; no local material injection.
        return None

    def encrypt(self, plaintext: bytes, *, key_id: str) -> bytes:
        resp = self._client.encrypt(KeyId=key_id, Plaintext=plaintext)
        return bytes(resp["CiphertextBlob"])

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> bytes:
        # KeyId optional for decrypt, included for explicit intent.
        resp = self._client.decrypt(CiphertextBlob=ciphertext, KeyId=key_id)
        return bytes(resp["Plaintext"])


class GcpKMSAdapter:
    provider = "gcp"

    def __init__(self) -> None:
        try:
            from google.cloud import kms  # type: ignore
        except Exception as exc:
            raise RuntimeError("GCP KMS adapter requires google-cloud-kms installed") from exc
        self._client = kms.KeyManagementServiceClient()

    def set_key_material(self, key_id: str, material: str) -> None:
        return None

    def encrypt(self, plaintext: bytes, *, key_id: str) -> bytes:
        # key_id must be full cryptoKey resource path.
        resp = self._client.encrypt(request={"name": key_id, "plaintext": plaintext})
        return bytes(resp.ciphertext)

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> bytes:
        resp = self._client.decrypt(request={"name": key_id, "ciphertext": ciphertext})
        return bytes(resp.plaintext)


class AzureKMSAdapter:
    provider = "azure"

    def __init__(self, *, vault_url: str, key_name: str, credential_mode: str = "default") -> None:
        try:
            from azure.identity import (  # type: ignore
                ClientSecretCredential,
                DefaultAzureCredential,
            )
            from azure.keyvault.keys import KeyClient  # type: ignore
            from azure.keyvault.keys.crypto import (  # type: ignore
                CryptographyClient,
                EncryptionAlgorithm,
            )
        except Exception as exc:
            raise RuntimeError(
                "Azure KMS adapter requires azure-keyvault + azure-identity packages"
            ) from exc

        if credential_mode == "client_secret":
            import os

            tenant_id = os.environ.get("AZURE_TENANT_ID", "")
            client_id = os.environ.get("AZURE_CLIENT_ID", "")
            client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
            cred = ClientSecretCredential(
                tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
            )
        else:
            cred = DefaultAzureCredential()
        key_client = KeyClient(vault_url=vault_url, credential=cred)
        key = key_client.get_key(key_name)
        self._crypto = CryptographyClient(key=key, credential=cred)
        self._alg = EncryptionAlgorithm.rsa_oaep_256

    def set_key_material(self, key_id: str, material: str) -> None:
        return None

    def encrypt(self, plaintext: bytes, *, key_id: str) -> bytes:
        resp = self._crypto.encrypt(self._alg, plaintext)
        return bytes(resp.ciphertext)

    def decrypt(self, ciphertext: bytes, *, key_id: str) -> bytes:
        resp = self._crypto.decrypt(self._alg, ciphertext)
        return bytes(resp.plaintext)
