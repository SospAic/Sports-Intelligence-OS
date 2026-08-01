"""Regression tests for honest account-monitoring status reporting.

A sync may finish with the account profile updated but per-account analytics
unavailable (e.g. a browser adapter that only resolves the profile, or a
rate-limited API). Previously the code forced ``account.sync_status = "success"``
in that case, falsifying the monitoring state. We now persist the real
``degraded`` status and surface an error code, so the UI can show
"部分同步（指标缺失）" instead of a misleading "监控中".
"""

import os
from datetime import UTC, datetime
from tempfile import mkstemp
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import PlatformAdapter, PlatformMetricsData
from app.adapters.platforms.mock import MockPlatformAdapter
from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor


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


def _empty_content_page() -> SimpleNamespace:
    return SimpleNamespace(items=[], next_cursor=None)


class DegradedMockAdapter(MockPlatformAdapter):
    """Mock adapter whose account analytics are unavailable (all-None)."""

    async def fetch_account_analytics(self, ctx, external_id):  # noqa: ANN001
        return PlatformMetricsData(
            external_id=external_id,
            captured_at=ctx.observed_at,
            metrics={
                "follower_count": None,
                "following_count": None,
                "total_like_count": None,
                "total_view_count": None,
                "video_count": None,
                "engagement_rate": None,
            },
            source_kind="mock",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={"demo": True},
        )

    async def list_contents(self, ctx, external_id, **kwargs):  # noqa: ANN001, ARG001
        return _empty_content_page()

    async def fetch_content_analytics(self, ctx, external_ids):  # noqa: ANN001, ARG001
        return ()


class ProfileOnlyMockAdapter(MockPlatformAdapter):
    """Mock adapter with working analytics so the account ends in 'success'."""

    async def list_contents(self, ctx, external_id, **kwargs):  # noqa: ANN001, ARG001
        return _empty_content_page()

    async def fetch_content_analytics(self, ctx, external_ids):  # noqa: ANN001, ARG001
        return ()


def _build_registry(adapter: PlatformAdapter) -> ProviderRegistry[PlatformAdapter]:
    registry: ProviderRegistry[PlatformAdapter] = ProviderRegistry()
    registry.register(adapter)
    return registry


async def _seed(session, workspace_id, platform_id, account_id, run_id) -> None:
    session.add(
        Workspace(
            id=workspace_id,
            name="ws",
            slug="ws",
            status="active",
            default_timezone="UTC",
            row_version=1,
        )
    )
    session.add(
        Platform(
            id=platform_id,
            key="test_platform",
            name="Test",
            category="video",
            enabled=True,
            adapter_key="mock_platform",
            capabilities={},
        )
    )
    session.add(
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
    session.add(
        SyncRun(
            id=run_id,
            workspace_id=workspace_id,
            target_type="account",
            target_id=account_id,
            adapter_key="mock_platform",
            request_id="req-degraded",
            queued_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
            status="queued",
            metadata_json={},
        )
    )
    await session.commit()


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

        registry = _build_registry(DegradedMockAdapter())

        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id)

        settings = _build_settings()
        async with maker() as session:
            executor = PlatformSyncExecutor(session, registry, settings)
            await executor.execute_account_run(run_id)

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

        registry = _build_registry(ProfileOnlyMockAdapter())

        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id)

        settings = _build_settings()
        async with maker() as session:
            executor = PlatformSyncExecutor(session, registry, settings)
            await executor.execute_account_run(run_id)

        async with maker() as session:
            account = await session.get(Account, account_id)
            assert account.sync_status == "success"
    finally:
        await engine.dispose()
        _cleanup(path)
