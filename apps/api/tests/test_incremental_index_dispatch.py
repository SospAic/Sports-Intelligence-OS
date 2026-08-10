"""Incremental indexing: content text changes queue the index task once.

Mirrors ``test_account_sync_e2e``'s session/executor harness but focuses on the
dispatch decision in ``PlatformSyncExecutor._flush_pending_indexing`` (no real
adapter, no network — we only assert the broker recorder is called correctly).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL, RealShapedTestAdapter

ADAPTER_KEY = "incr_adapter"
PLATFORM_KEY = "incr_platform"


def _settings(enabled: bool) -> Settings:
    s = Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )
    s.semantic_search_enabled = enabled
    s.embedding_backend = "tei" if enabled else "none"
    return s


def _registry() -> ProviderRegistry:
    registry: ProviderRegistry = ProviderRegistry()
    registry.register(RealShapedTestAdapter(key=ADAPTER_KEY))
    return registry


async def _with_session(work):
    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            await work(session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_flush_dispatches_when_semantic_search_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.embedding import index_content_item

    dispatched: list[str] = []
    monkeypatch.setattr(index_content_item, "delay", lambda cid: dispatched.append(cid))

    cid = uuid4()

    async def _body(session):
        executor = PlatformSyncExecutor(session, _registry(), _settings(enabled=True))
        executor._pending_index_ids = [cid]
        await executor._flush_pending_indexing()

    await _with_session(_body)
    assert dispatched == [str(cid)]


@pytest.mark.asyncio
async def test_flush_skips_when_semantic_search_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.embedding import index_content_item

    dispatched: list[str] = []
    monkeypatch.setattr(index_content_item, "delay", lambda cid: dispatched.append(cid))

    cid = uuid4()

    async def _body(session):
        executor = PlatformSyncExecutor(session, _registry(), _settings(enabled=False))
        executor._pending_index_ids = [cid]
        await executor._flush_pending_indexing()

    await _with_session(_body)
    assert dispatched == []
