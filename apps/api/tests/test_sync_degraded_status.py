"""Regression tests for honest account-monitoring status reporting.

A sync may finish with the account profile updated but per-account analytics
unavailable (e.g. a browser adapter that only resolves the profile, or a
rate-limited API). Previously the code forced ``account.sync_status = "success"``
in that case, falsifying the monitoring state. We now persist the real
``degraded`` status and surface an error code, so the UI can show
"部分同步（指标缺失）" instead of a misleading "监控中".

These tests drive a REAL adapter shape (``source_kind="live"``) via a small
test-only fixture adapter (``RealShapedTestAdapter`` in conftest) that is never
registered in production. They assert the sync engine's status *decision* logic,
not any live data. A separate test asserts that a skeleton adapter — which
performs no live requests — ends the sync in ``error`` and releases the account
lock, i.e. the system never reports "success" when no real data could be fetched.
"""

import os
from datetime import UTC, datetime
from tempfile import mkstemp
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import AdapterCapability, AdapterDescriptor
from app.adapters.platforms.stubs import SkeletonPlatformAdapter
from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor

from .conftest import RealShapedTestAdapter

ADAPTER_KEY = "test_sync_adapter"
SKELETON_KEY = "skeleton_test"


def _cleanup(path: str) -> None:
    """Remove the temporary sqlite file (sync helper avoids ASYNC240)."""
    try:
        os.remove(path)
    except OSError:
        pass


def _build_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )


def _build_registry(adapter: object) -> ProviderRegistry:
    registry: ProviderRegistry = ProviderRegistry()
    registry.register(adapter)  # type: ignore[arg-type]
    return registry


async def _seed(
    session: object,
    workspace_id: object,
    platform_id: object,
    account_id: object,
    run_id: object,
    adapter_key: str,
) -> None:
    s = session  # type: ignore[assignment]
    s.add(
        Workspace(
            id=workspace_id,
            name="ws",
            slug="ws",
            status="active",
            default_timezone="UTC",
            row_version=1,
        )
    )
    s.add(
        Platform(
            id=platform_id,
            key="test_platform",
            name="Test",
            category="video",
            enabled=True,
            adapter_key=adapter_key,
            capabilities={},
        )
    )
    s.add(
        Account(
            id=account_id,
            workspace_id=workspace_id,
            platform_id=platform_id,
            external_id="external-001",
            display_name="测试账号",
            source_kind="imported",
            source_provider="manual",
            fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
    )
    s.add(
        SyncRun(
            id=run_id,
            workspace_id=workspace_id,
            target_type="account",
            target_id=account_id,
            adapter_key=adapter_key,
            request_id="req-degraded",
            queued_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
            status="queued",
            metadata_json={},
        )
    )
    await s.commit()


async def test_degraded_sync_account_status_is_degraded() -> None:
    """When account analytics are unavailable, account.sync_status must be the
    honest 'degraded' value (not a falsified 'success')."""
    fd, path = mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        workspace_id = uuid4()
        platform_id = uuid4()
        account_id = uuid4()
        run_id = uuid4()

        registry = _build_registry(RealShapedTestAdapter(analytics_all_none=True))

        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

        settings = _build_settings()
        async with maker() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

        async with maker() as session:
            account = await session.get(Account, account_id)
            run = await session.get(SyncRun, run_id)
            assert run.status == "degraded"
            assert account.sync_status == "degraded", (
                "degraded sync must not falsify account.sync_status as 'success'"
            )
            assert account.last_sync_error_code == "account_metrics_extraction_failed"
    finally:
        await engine.dispose()
        _cleanup(path)


async def test_successful_sync_account_status_is_success() -> None:
    """Sanity check: when analytics are available, the account ends in 'success'."""
    fd, path = mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        workspace_id = uuid4()
        platform_id = uuid4()
        account_id = uuid4()
        run_id = uuid4()

        registry = _build_registry(RealShapedTestAdapter(analytics_all_none=False))

        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

        settings = _build_settings()
        async with maker() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

        async with maker() as session:
            account = await session.get(Account, account_id)
            assert account.sync_status == "success"
    finally:
        await engine.dispose()
        _cleanup(path)


class _SkeletonTestAdapter(SkeletonPlatformAdapter):
    descriptor = AdapterDescriptor(
        key=SKELETON_KEY,
        name="Skeleton Test",
        implementation_status="skeleton",
        capabilities={capability: False for capability in AdapterCapability},
        config_fields=(),
        source_kinds=frozenset({"live"}),
    )


async def test_skeleton_adapter_sync_ends_in_error_and_releases_lock() -> None:
    """A skeleton adapter performs no live requests. The sync must end in 'error'
    (never 'success'), and the account lock must be released so the account is
    not permanently stuck. This guards the real-data contract: no live data ->
    no fake success, and the lock is never held forever."""
    fd, path = mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        workspace_id = uuid4()
        platform_id = uuid4()
        account_id = uuid4()
        run_id = uuid4()

        registry = _build_registry(_SkeletonTestAdapter())

        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id, SKELETON_KEY)

        settings = _build_settings()
        async with maker() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

        async with maker() as session:
            account = await session.get(Account, account_id)
            run = await session.get(SyncRun, run_id)
            assert run.status == "error", "skeleton adapter must not report success"
            assert account.sync_status == "error"
            assert run.lock_key is None, "account lock must be released after a failed sync"
            assert account.last_sync_error_code is not None
    finally:
        await engine.dispose()
        _cleanup(path)
