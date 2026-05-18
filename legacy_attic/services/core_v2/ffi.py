from __future__ import annotations

import json

import structlog
import rust_engine

logger = structlog.get_logger(__name__)


def run_rules(payload_dict: dict) -> str:
    """Serialize `payload_dict` to JSON and evaluate it via the Rust `rust_engine` module."""
    try:
        payload_json = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        logger.error(
            "payload_json_encoding_failed",
            exc_info=exc,
        )
        raise ValueError("payload cannot be encoded as JSON") from exc

    try:
        return rust_engine.evaluate_transaction(payload_json)
    except Exception as exc:
        logger.error(
            "rust_engine_evaluate_transaction_failed",
            exc_info=exc,
        )
        raise ValueError("rule evaluation failed") from exc
