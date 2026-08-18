"""Cross-worker sync lease behaviour against the Compose Redis service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.services.sync_lease import SyncConcurrencyLease, SyncLeaseUnavailable, _safe_part


def test_safe_part_keeps_redis_key_components_bounded() -> None:
    assert _safe_part(" YouTube/YTDLP ") == "youtube_ytdlp"
    assert len(_safe_part("x" * 200)) <= 80


@pytest.mark.asyncio
async def test_global_and_platform_slots_are_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={
            "sync_global_concurrency": 1,
            "sync_platform_concurrency": 1,
            "sync_lease_wait_seconds": 1,
        }
    )
    namespace = f"sio:test:lease:{uuid4()}"
    first = SyncConcurrencyLease(settings)
    second = SyncConcurrencyLease(settings)
    for lease in (first, second):
        monkeypatch.setattr(lease, "_global_key", lambda slot, p=namespace: f"{p}:global:{slot}")
        monkeypatch.setattr(
            lease,
            "_platform_key",
            lambda platform, slot, p=namespace: f"{p}:platform:{slot}",
        )

    try:
        await first.acquire(uuid4(), "youtube_ytdlp")
        with pytest.raises(SyncLeaseUnavailable):
            await second.acquire(uuid4(), "youtube_ytdlp")
        await first.release()
        released = await second.acquire(uuid4(), "youtube_ytdlp")
        assert released.waited_seconds >= 0
    finally:
        await first.release()
        await second.release()
