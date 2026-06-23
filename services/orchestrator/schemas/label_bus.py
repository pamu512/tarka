"""Pydantic validation for enriched label payloads emitted to ``tarka.events.labels``."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from messaging.labels_jetstream import NORMALIZED_LABEL_EVENT_SCHEMA

LABEL_BUS_STRUCTURAL_TAG_RE = re.compile(r"^[a-z0-9_-]+:[a-z0-9_-]+$")
VALID_LABEL_BUS_GROUND_TRUTH = frozenset({"FRAUD", "LEGITIMATE"})


class LabelBusValidationError(ValueError):
    """Raised when a label bus emit payload fails runtime validation."""


class LabelBusEmitPayload(BaseModel):
    """Runtime gate for payloads published onto the label JetStream bus."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    payload_schema: Literal["tarka.normalized_label.v1"] = Field(
        ...,
        serialization_alias="schema",
        validation_alias="schema",
    )
    id: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., min_length=1, max_length=64)
    source_id: str = Field(..., min_length=1, max_length=128)
    entity_id: str = Field(..., min_length=1, max_length=512)
    ground_truth_class: Literal["FRAUD", "LEGITIMATE"]
    tags: list[str] = Field(..., min_length=1, max_length=128)
    propagated_to_consortium: bool = True
    created_at: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("entity_id")
    @classmethod
    def _entity_id_non_empty(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("entity_id must be a non-empty string")
        return token

    @field_validator("tags")
    @classmethod
    def _tags_match_structural_standard(cls, tags: list[str]) -> list[str]:
        if not tags:
            raise ValueError("at least one structural tag is required for label bus emit")
        out: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            token = str(raw or "").strip()
            if not token:
                raise ValueError("structural tags must be non-empty strings")
            if not LABEL_BUS_STRUCTURAL_TAG_RE.fullmatch(token):
                raise ValueError(
                    f"tag {token!r} must match ^[a-z0-9_-]+:[a-z0-9_-]+$",
                )
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
        if not out:
            raise ValueError("at least one unique structural tag is required")
        return out


def filter_structural_tags(raw_tags: list[str] | None) -> list[str]:
    """Return deduplicated tags that satisfy the label-bus structural naming standard."""
    if not raw_tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        token = str(raw or "").strip()
        if not token or not LABEL_BUS_STRUCTURAL_TAG_RE.fullmatch(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def build_label_bus_emit_dict(row: Any) -> dict[str, Any]:
    """Build a candidate label-bus payload from a ``NormalizedLabelORM`` row."""
    from messaging.labels_jetstream import (
        normalized_label_event_entity,
    )  # noqa: PLC0415

    payload = normalized_label_event_entity(row)
    payload["tags"] = filter_structural_tags(list(payload.get("tags") or []))
    gt = str(payload.get("ground_truth_class") or "").strip().upper()
    if gt in VALID_LABEL_BUS_GROUND_TRUTH:
        payload["ground_truth_class"] = gt
    return payload


def validate_label_bus_emit_payload(raw: dict[str, Any]) -> LabelBusEmitPayload:
    """Validate a label bus payload; raises :class:`LabelBusValidationError` on failure."""
    try:
        return LabelBusEmitPayload.model_validate(raw)
    except Exception as exc:
        raise LabelBusValidationError(str(exc)) from exc


def validate_structural_tag_list(tags: list[str]) -> list[str]:
    """Validate retroactive / appended structural tags before persistence."""
    try:
        validated = LabelBusEmitPayload.model_validate(
            {
                "schema": NORMALIZED_LABEL_EVENT_SCHEMA,
                "id": "00000000-0000-0000-0000-000000000001",
                "source_type": "VALIDATION_PROBE",
                "source_id": "00000000-0000-0000-0000-000000000002",
                "entity_id": "validation-probe-entity",
                "ground_truth_class": "FRAUD",
                "tags": tags,
                "propagated_to_consortium": True,
            },
        )
    except Exception as exc:
        raise LabelBusValidationError(str(exc)) from exc
    return list(validated.tags)
