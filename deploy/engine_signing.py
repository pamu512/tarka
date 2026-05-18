"""Rust engine signing secret for Triple-DB Pulumi (``tarka`` / ``tarka-core`` Ed25519ph Merkle signing).

The stack secret ``triple-db:tarkaSigningKey`` must be a **hex-encoded 32-byte** Ed25519 seed (64 hex
characters). It is surfaced to workloads as environment variable **`TARKA_SIGNING_KEY`**, which
``tarka_core::crypto::try_local_ed25519_ph_signer_from_env`` reads before falling back to KMS.

Configure::

    pulumi config set --secret triple-db:tarkaSigningKey '<64-char-hex>'

When ``triple-db:createEngineSigningKubernetesSecret`` is not ``false`` and the secret is set,
this module creates Kubernetes ``Secret`` ``tarka-engine-signing`` in namespace
``triple-db:engineNamespace`` (else ``redisNamespace``, else ``tarka``) with string data key
``TARKA_SIGNING_KEY``. Mount it from decision-api (see ``deploy/hosted/k8s/base/decision-api-deployment.yaml``).
"""

from __future__ import annotations

import pulumi
from pulumi_kubernetes.core.v1 import Secret
from pulumi_kubernetes.meta.v1 import ObjectMetaArgs

_MANAGED_BY = "pulumi-triple-db"
_SECRET_NAME = "tarka-engine-signing"


def provision(*, cfg: pulumi.Config | None = None) -> None:
    """Create a Kubernetes Secret for ``TARKA_SIGNING_KEY`` when stack secret is configured."""
    cfg = cfg or pulumi.Config()
    key = cfg.get_secret("tarkaSigningKey")
    if key is None:
        pulumi.log.info(
            "triple-db:tarkaSigningKey unset — set with: "
            "pulumi config set --secret triple-db:tarkaSigningKey '<64-hex Ed25519 seed>'"
        )
        return

    if cfg.get_bool("createEngineSigningKubernetesSecret") is False:
        pulumi.log.info(
            "triple-db:createEngineSigningKubernetesSecret is false; "
            "stack secret tarkaSigningKey is not materialized as a Kubernetes Secret "
            "(inject TARKA_SIGNING_KEY via your runtime)."
        )
        return

    ns = cfg.get("engineNamespace") or cfg.get("redisNamespace") or "tarka"
    labels = {"managed-by": _MANAGED_BY, "tarka.io/component": "engine-signing"}

    string_data = pulumi.Output.all(key).apply(lambda parts: {"TARKA_SIGNING_KEY": parts[0]})

    Secret(
        "triple-db-tarka-engine-signing",
        metadata=ObjectMetaArgs(
            name=_SECRET_NAME,
            namespace=ns,
            labels=labels,
        ),
        string_data=string_data,
    )

    pulumi.export("engineSigningSecretName", _SECRET_NAME)
    pulumi.export("engineSigningSecretNamespace", ns)
