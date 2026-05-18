"""Tests for SQLite-backed messaging buffer / replay (tarka_core.messaging)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tarka_core.messaging import (
    EphemeralDiskBufferBroker,
    MessageBroker,
    PublishDelivery,
    replay_disk_buffer_to_broker,
)


class _CaptureBroker(MessageBroker):
    def __init__(self) -> None:
        self.items: list[tuple[str, bytes, PublishDelivery]] = []

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        delivery: PublishDelivery = PublishDelivery.JETSTREAM,
    ) -> None:
        self.items.append((subject, payload, delivery))

    async def subscribe(self, subject: str, handler):  # noqa: ANN001
        return None

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_ephemeral_buffer_persists_and_replay_marks_flushed(
    tmp_path: Path,
) -> None:
    db = tmp_path / "buf.db"
    br = EphemeralDiskBufferBroker(db)
    await br.publish("eval.done", b'{"x":1}', delivery=PublishDelivery.JETSTREAM)
    await br.aclose()

    jlog = db.with_suffix(db.suffix + ".jlog")
    assert jlog.is_file() and jlog.stat().st_size > 0

    cap = _CaptureBroker()
    n = await replay_disk_buffer_to_broker(db, cap)
    assert n == 1
    assert cap.items == [("eval.done", b'{"x":1}', PublishDelivery.JETSTREAM)]

    cap2 = _CaptureBroker()
    assert await replay_disk_buffer_to_broker(db, cap2) == 0


@pytest.mark.asyncio
async def test_replay_stops_on_target_failure(tmp_path: Path) -> None:
    db = tmp_path / "buf.db"
    br = EphemeralDiskBufferBroker(db)
    await br.publish("a", b"1")
    await br.publish("b", b"2")
    await br.aclose()

    class FailSecond(_CaptureBroker):
        def __init__(self) -> None:
            super().__init__()
            self._n = 0

        async def publish(
            self, subject, payload, *, delivery=PublishDelivery.JETSTREAM
        ):  # noqa: ANN001
            self._n += 1
            if self._n == 2:
                raise RuntimeError("simulated NATS outage")
            await super().publish(subject, payload, delivery=delivery)

    fb = FailSecond()
    n = await replay_disk_buffer_to_broker(db, fb)
    assert n == 1
    assert len(fb.items) == 1

    ok = _CaptureBroker()
    rest = await replay_disk_buffer_to_broker(db, ok)
    assert rest == 1
    assert ok.items[0][0] == "b"
