"""ONNX Model Registry with versioning and A/B traffic splitting.

Models are stored on disk at:
    models/{model_name}/{version}/model.onnx
    models/{model_name}/{version}/metadata.json

Each model version carries a ``traffic_weight`` (0-100) used for A/B
routing.  The registry selects a model probabilistically based on the
normalised weights of all *active* versions.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("ml-scoring.registry")


@dataclass
class ModelVersion:
    name: str
    version: int
    path: Path
    metadata: dict[str, Any]
    traffic_weight: int = 0
    active: bool = True
    onnx_session: Any = field(default=None, repr=False)
    onnx_input_name: str = ""
    # runtime stats
    total_inferences: int = 0
    total_latency_ms: float = 0.0
    last_used: float = 0.0


class ModelRegistry:
    """Manages multiple ONNX (or heuristic) model versions."""

    def __init__(self, models_dir: str | Path = "models") -> None:
        self._models_dir = Path(models_dir)
        self._versions: dict[str, dict[int, ModelVersion]] = {}
        self._active_model: str | None = None

    # ------------------------------------------------------------------
    # Discovery & loading
    # ------------------------------------------------------------------

    def scan(self) -> int:
        """Walk ``models_dir`` and register every version found.

        Returns the number of versions loaded.
        """
        count = 0
        if not self._models_dir.is_dir():
            log.warning("models dir %s does not exist", self._models_dir)
            return 0

        for model_dir in sorted(self._models_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            model_name = model_dir.name
            for ver_dir in sorted(model_dir.iterdir()):
                if not ver_dir.is_dir():
                    continue
                try:
                    version = int(ver_dir.name)
                except ValueError:
                    continue
                meta_path = ver_dir / "metadata.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    log.warning("skipping %s/%s: %s", model_name, version, exc)
                    continue

                mv = ModelVersion(
                    name=model_name,
                    version=version,
                    path=ver_dir,
                    metadata=meta,
                    traffic_weight=int(meta.get("traffic_weight", 0)),
                    active=bool(meta.get("active", True)),
                )

                onnx_path = ver_dir / "model.onnx"
                if onnx_path.exists():
                    mv = self._load_onnx(mv, onnx_path)

                self._versions.setdefault(model_name, {})[version] = mv
                if self._active_model is None:
                    self._active_model = model_name
                count += 1
                log.info(
                    "registered model %s v%d  weight=%d active=%s onnx=%s",
                    model_name, version, mv.traffic_weight, mv.active,
                    mv.onnx_session is not None,
                )
        return count

    @staticmethod
    def _load_onnx(mv: ModelVersion, onnx_path: Path) -> ModelVersion:
        try:
            import onnxruntime as ort

            mv.onnx_session = ort.InferenceSession(
                str(onnx_path), providers=["CPUExecutionProvider"]
            )
            mv.onnx_input_name = mv.onnx_session.get_inputs()[0].name
        except Exception as exc:
            log.warning("could not load ONNX for %s v%d: %s", mv.name, mv.version, exc)
        return mv

    # ------------------------------------------------------------------
    # A/B selection
    # ------------------------------------------------------------------

    def get_model(self, tenant_id: str) -> tuple[ModelVersion | None, str, int]:
        """Pick a model version for *tenant_id* based on traffic weights.

        Returns ``(ModelVersion | None, model_name, version)``.
        Uses a deterministic seed derived from ``tenant_id`` so the same
        tenant always lands on the same variant within a given weight
        configuration.
        """
        if not self._versions:
            return None, "", 0

        model_name = self._active_model or next(iter(self._versions))
        versions = self._versions.get(model_name, {})
        active = [v for v in versions.values() if v.active and v.traffic_weight > 0]
        if not active:
            fallback = max(versions.values(), key=lambda v: v.version) if versions else None
            return fallback, model_name, (fallback.version if fallback else 0)

        total = sum(v.traffic_weight for v in active)
        seed = int(hashlib.sha256(tenant_id.encode()).hexdigest(), 16)
        rng = random.Random(seed)
        pick = rng.randint(1, total)
        cumulative = 0
        for v in sorted(active, key=lambda x: x.version):
            cumulative += v.traffic_weight
            if pick <= cumulative:
                return v, model_name, v.version

        return active[-1], model_name, active[-1].version

    # ------------------------------------------------------------------
    # Model management helpers
    # ------------------------------------------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for model_name, versions in sorted(self._versions.items()):
            for ver, mv in sorted(versions.items()):
                result.append({
                    "model_name": mv.name,
                    "version": mv.version,
                    "traffic_weight": mv.traffic_weight,
                    "active": mv.active,
                    "has_onnx": mv.onnx_session is not None,
                    "total_inferences": mv.total_inferences,
                    "avg_latency_ms": (
                        round(mv.total_latency_ms / mv.total_inferences, 2)
                        if mv.total_inferences else 0
                    ),
                    "metadata": mv.metadata,
                })
        return result

    def activate_version(self, model_name: str, version: int) -> bool:
        """Set *version* as the sole active version for *model_name*."""
        versions = self._versions.get(model_name)
        if not versions or version not in versions:
            return False
        for v, mv in versions.items():
            mv.active = v == version
            mv.traffic_weight = 100 if v == version else 0
        self._active_model = model_name
        self._persist_metadata(model_name)
        return True

    def get_model_stats(self, model_name: str) -> list[dict[str, Any]]:
        versions = self._versions.get(model_name, {})
        return [
            {
                "version": mv.version,
                "active": mv.active,
                "traffic_weight": mv.traffic_weight,
                "total_inferences": mv.total_inferences,
                "avg_latency_ms": (
                    round(mv.total_latency_ms / mv.total_inferences, 2)
                    if mv.total_inferences else 0
                ),
                "last_used": mv.last_used,
            }
            for mv in sorted(versions.values(), key=lambda x: x.version)
        ]

    def record_inference(self, model_name: str, version: int, latency_ms: float) -> None:
        mv = self._versions.get(model_name, {}).get(version)
        if mv:
            mv.total_inferences += 1
            mv.total_latency_ms += latency_ms
            mv.last_used = time.time()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_metadata(self, model_name: str) -> None:
        """Write updated metadata back to disk."""
        for mv in self._versions.get(model_name, {}).values():
            meta_path = mv.path / "metadata.json"
            try:
                meta = dict(mv.metadata)
                meta["traffic_weight"] = mv.traffic_weight
                meta["active"] = mv.active
                meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                log.warning("could not persist metadata for %s v%d: %s", model_name, mv.version, exc)
