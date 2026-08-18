"""Concurrency / deadlock / timeout stress tests for the account sync path.

These guard the "killed pytest leaves dangling PG locks -> next run deadlocks"
class of failures (see project memory). They run the *real*
:class:`PlatformSyncExecutor` in-process with a faked broker, like
``test_account_sync_e2e.py``, but drive many runs concurrently and wrap every
execution in a wall-clock budget so a hang fails the test instead of the suite.

No network / no browser: adapters are shaped doubles.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import (
    AdapterCallContext,
    LoginRequiredError,
    PlatformAccountData,
)
from app.core.config import Settings
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL, RealShapedTestAdapter

PLATFORM_KEY = "stress_platform"
ADAPTER_KEY = "stress_adapter"


def _build_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )


def _build_registry(adapter: object) -> ProviderRegistry:
    registry: ProviderRegistry = ProviderRegistry()
    registry.register(adapter)  # type: ignore[arg-type]
    return registry


class _WalledAdapter(RealShapedTestAdapter):
    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        raise LoginRequiredError(PLATFORM_KEY, "登录墙拦截了公开页采集")


class _SlowAdapter(RealShapedTestAdapter):
    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        # Deliberately exceeds any reasonable sync budget to prove the executor
        # does not swallow cancellation and hang forever.
        await asyncio.sleep(30)
        raise LoginRequiredError(PLATFORM_KEY, "never reached")


async def _seed_and_run(
    engine_uri: str,
    workspace_id: UUID,
    platform_id: UUID,
    account_id: UUID,
    run_id: UUID,
    adapter: object,
    platform_key: str,
) -> object:
    """Seed the workspace/platform/account/run and run the sync in ONE session.

    Mirrors ``test_account_sync_e2e``'s ``_body`` (seed + execute share a session
    and engine) so the FK chain commits atomically before the executor reads it.
    Returns the engine so the caller can dispose it after the concurrency window
    (disposing inside the task's ``finally`` races with loop teardown under
    pytest-asyncio and raises ``CancelledError``).
    """

    engine = create_async_engine(engine_uri)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        # Two-phase commit (as in test_account_sync_e2e): persist the parents
        # first, then the run, so SQLAlchemy flushes the workspace before the
        # sync_runs FK is checked.
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="ws",
                    slug=f"ws-{workspace_id.hex[:8]}",
                    status="active",
                    default_timezone="UTC",
                    row_version=1,
                ),
                Platform(
                    id=platform_id,
                    key=platform_key,
                    name="Stress",
                    category="video",
                    enabled=True,
                    adapter_key=ADAPTER_KEY,
                    capabilities={},
                ),
                Account(
                    id=account_id,
                    workspace_id=workspace_id,
                    platform_id=platform_id,
                    external_id=f"ext-{account_id.hex[:8]}",
                    display_name="压测账号",
                    source_kind="imported",
                    source_provider="manual",
                    sync_status="never",
                    fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()

        session.add(
            SyncRun(
                id=run_id,
                workspace_id=workspace_id,
                target_type="account",
                target_id=account_id,
                adapter_key=ADAPTER_KEY,
                request_id=f"req-{run_id.hex[:8]}",
                queued_at=datetime.now(UTC),
                status="queued",
                lock_key=f"account:{account_id}",
            )
        )
        await session.commit()

        executor = PlatformSyncExecutor(session, _build_registry(adapter), _build_settings())
        await executor.execute_account_run(run_id)
    return engine  # caller disposes after the concurrency window


@pytest.mark.asyncio
async def test_concurrent_sync_runs_complete_without_deadlock() -> None:
    """N account syncs fire in parallel; every run must reach a terminal state
    and release its lock within the wall-clock budget (no deadlock, no serial
    blow-up)."""

    n = 12
    # All login-wall fast-fails: the executor closes each run *terminal* (no
    # Celery retry ladder involved), so every task returns normally and we can
    # assert the locks are released. The transient retry-exhaust path is covered
    # separately by ``test_account_sync_e2e``'s retry ladder. Each run gets a
    # UNIQUE platform key to dodge the ``uq_platforms_key`` collision when 12
    # tasks insert in parallel.
    adapters = [_WalledAdapter(key=ADAPTER_KEY) for _ in range(n)]
    specs = [
        (uuid4(), uuid4(), uuid4(), uuid4(), adapter, f"{PLATFORM_KEY}_{i}")
        for i, adapter in enumerate(adapters)
    ]

    tasks = [
        _seed_and_run(PG_ASYNC_URL, ws, pf, acc, run, adapter, pkey)
        for (ws, pf, acc, run, adapter, pkey) in specs
    ]

    # The whole batch must finish well under the per-run retry backoff ceiling.
    # Each task returns its engine; dispose them after the window so teardown
    # does not race with the event loop shutdown.
    engines = await asyncio.wait_for(asyncio.gather(*tasks), timeout=60)
    for eng in engines:
        await eng.dispose()

    verify_engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(verify_engine, expire_on_commit=False)
    try:
        async with maker() as session:
            ids = [run for (_, _, _, run, _, _) in specs]
            stored = (await session.scalars(select(SyncRun).where(SyncRun.id.in_(ids)))).all()
            assert len(stored) == n
            for r in stored:
                assert r.status in {"success", "error"}, f"run {r.id} stuck at {r.status}"
                assert r.lock_key is None, f"run {r.id} never released its lock"
                assert r.finished_at is not None
    finally:
        await verify_engine.dispose()


@pytest.mark.asyncio
async def test_sync_run_does_not_hang_indefinitely() -> None:
    """A pathologically slow adapter must not hang the worker forever: the
    execution is cancellable and surfaces as a timeout rather than a silent
    stall."""

    ws, pf, acc, run = uuid4(), uuid4(), uuid4(), uuid4()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            _seed_and_run(
                PG_ASYNC_URL, ws, pf, acc, run, _SlowAdapter(key=ADAPTER_KEY), PLATFORM_KEY
            ),
            timeout=3,
        )
