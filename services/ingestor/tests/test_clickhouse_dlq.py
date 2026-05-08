"""ClickHouse ingest retries and DLQ boundary."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from clickhouse_connect.driver.exceptions import ClickHouseError
from ingestor.clickhouse_sink import insert_evidence_manifest
from ingestor.settings import IngestorSettings


def test_insert_evidence_manifest_respects_max_attempts() -> None:
    settings = IngestorSettings(clickhouse_insert_max_attempts=3)
    client = MagicMock()
    attempts = {"n": 0}

    def _boom(
        _client: MagicMock,
        _settings: IngestorSettings,
        _row: dict[str, object],
    ) -> None:
        attempts["n"] += 1
        raise ClickHouseError("simulated ClickHouse failure")

    with (
        patch(
            "ingestor.clickhouse_sink._insert_evidence_manifest_once",
            side_effect=_boom,
        ),
        patch("ingestor.clickhouse_sink.time.sleep"),
    ):
        with pytest.raises(ClickHouseError):
            insert_evidence_manifest(client, settings, {})

    assert attempts["n"] == 3


def test_insert_evidence_manifest_succeeds_on_partial_failures() -> None:
    settings = IngestorSettings(clickhouse_insert_max_attempts=3)
    client = MagicMock()
    attempts = {"n": 0}

    def _maybe(
        _client: MagicMock,
        _settings: IngestorSettings,
        _row: dict[str, object],
    ) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ClickHouseError("transient")

    with (
        patch(
            "ingestor.clickhouse_sink._insert_evidence_manifest_once",
            side_effect=_maybe,
        ),
        patch("ingestor.clickhouse_sink.time.sleep"),
    ):
        insert_evidence_manifest(client, settings, {})

    assert attempts["n"] == 3
