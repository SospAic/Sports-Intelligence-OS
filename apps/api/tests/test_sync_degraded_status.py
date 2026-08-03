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

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterDescriptor,
)
from app.adapters.platforms.stubs import SkeletonPlatformAdapter
from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor, SyncService

from .conftest import PG_ASYNC_URL, RealShapedTestAdapter

ADAPTER_KEY = "test_sync_adapter"
SKELETON_KEY = "skeleton_test"


def _build_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
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
    # Stage 1: persist the parent rows (workspace/platform/account) first.
    # PostgreSQL enforces foreign-key constraints (SQLite did not), so the
    # SyncRun that references them must be inserted only after they exist.
    s.add_all(
        [
            Workspace(
                id=workspace_id,
                name="ws",
                slug="ws",
                status="active",
                default_timezone="UTC",
                row_version=1,
            ),
            Platform(
                id=platform_id,
                key="test_platform",
                name="Test",
                category="video",
                enabled=True,
                adapter_key=adapter_key,
                capabilities={},
            ),
            Account(
                id=account_id,
                workspace_id=workspace_id,
                platform_id=platform_id,
                external_id="external-001",
                display_name="测试账号",
                source_kind="imported",
                source_provider="manual",
                fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ]
    )
    await s.commit()
    # Stage 2: insert the sync run that references the rows above.
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
    engine = create_async_engine(PG_ASYNC_URL)
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
    await engine.dispose()


async def test_successful_sync_account_status_is_success() -> None:
    """Sanity check: when analytics are available, the account ends in 'success'."""
    engine = create_async_engine(PG_ASYNC_URL)
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
    await engine.dispose()


class _SkeletonTestAdapter(SkeletonPlatformAdapter):
    descriptor = AdapterDescriptor(
        key=SKELETON_KEY,
        name="Skeleton Test",
        implementation_status="skeleton",
        capabilities={capability: False for capability in AdapterCapability},
        config_fields=(),
        source_kinds=frozenset({"live"}),
    )


class _PartialAnalyticsTestAdapter(RealShapedTestAdapter):
    """Simulates a yt-dlp-style adapter that fetched successfully but the
    platform (TikTok/Douyin) omits follower/video/view counts. The fetch is
    genuinely successful — the missing fields are a platform limitation, not a
    failed extraction — so ``analytics_fetched`` is True and the missing fields
    ride along in ``unavailable_metrics``."""

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> "PlatformMetricsData":  # type: ignore[name-defined]  # noqa: F821
        from app.adapters.platforms.base import PlatformMetricsData

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
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            unavailable_metrics=("follower_count", "video_count", "total_view_count"),
            metadata={"method": "yt_dlp", "analytics_fetched": True},
        )


async def test_partial_analytics_successful_fetch_is_success_not_degraded() -> None:
    """Regression: a successful yt-dlp fetch whose platform omits some metrics
    (TikTok/Douyin) must end as 'success' (with unavailable_metrics), NOT
    'degraded'. Previously the 'all key metrics None' heuristic falsely flagged
    every TikTok/Douyin sync as a failed metric extraction, so the UI showed
    '同步失败 / 指标提取失败，仅更新了账号资料' on every run."""
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    run_id = uuid4()

    registry = _build_registry(_PartialAnalyticsTestAdapter())
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

    settings = _build_settings()
    async with maker() as session:
        await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

    async with maker() as session:
        account = await session.get(Account, account_id)
        run = await session.get(SyncRun, run_id)
        assert run.status == "success", run.error_message
        assert account.sync_status == "success"
        assert account.last_sync_error_code is None
        assert account.last_sync_error_message is None
    await engine.dispose()


async def test_skeleton_adapter_sync_ends_in_error_and_releases_lock() -> None:
    """A skeleton adapter performs no live requests. The sync must end in 'error'
    (never 'success'), and the account lock must be released so the account is
    not permanently stuck. This guards the real-data contract: no live data ->
    no fake success, and the lock is never held forever."""
    engine = create_async_engine(PG_ASYNC_URL)
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
    await engine.dispose()


async def test_recover_stale_orphan_without_lock_key() -> None:
    """A run stuck in 'running' whose worker died *before* recording a lock_key
    (lock_key IS NULL) must still be recovered. Otherwise the account shows
    'syncing' forever even though a new sync is allowed (dedup is by lock_key,
    so an empty lock_key never blocks re-sync) — a confusing, stuck state."""
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    run_id = uuid4()
    registry = _build_registry(RealShapedTestAdapter())

    async with maker() as session:
        s = session
        s.add_all(
            [
                Workspace(
                    id=workspace_id, name="ws", slug="ws", status="active",
                    default_timezone="UTC", row_version=1,
                ),
                Platform(
                    id=platform_id, key="test_platform", name="Test", category="video",
                    enabled=True, adapter_key=ADAPTER_KEY, capabilities={},
                ),
                Account(
                    id=account_id, workspace_id=workspace_id, platform_id=platform_id,
                    external_id="external-orphan", display_name="孤儿账号",
                    source_kind="imported", source_provider="manual",
                    fetched_at=datetime(2026, 7, 1, tzinfo=UTC), sync_status="syncing",
                ),
            ]
        )
        await s.commit()
        s.add(
            SyncRun(
                id=run_id, workspace_id=workspace_id, target_type="account",
                target_id=account_id, adapter_key=ADAPTER_KEY, request_id="req-orphan",
                queued_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
                started_at=datetime(2026, 7, 25, 12, 5, tzinfo=UTC),
                status="running", lock_key=None, metadata_json={},
            )
        )
        await s.commit()

    settings = _build_settings()
    async with maker() as session:
        recovered = await SyncService(session, registry, settings).recover_stale_runs(
            stale_before=datetime(2026, 8, 1, tzinfo=UTC),
        )
        assert recovered == 1

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        assert run.status == "error"
        assert run.lock_key is None
        assert account.sync_status == "error"
    await engine.dispose()


async def test_recover_stale_orphan_keeps_newer_completed_status() -> None:
    """When a stale orphan exists but a *newer* run already completed, the
    recovery must close the orphan without clobbering the account's settled
    status (e.g. 'success')."""
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    orphan_id = uuid4()
    newer_id = uuid4()
    registry = _build_registry(RealShapedTestAdapter())

    async with maker() as session:
        s = session
        s.add_all(
            [
                Workspace(
                    id=workspace_id, name="ws", slug="ws", status="active",
                    default_timezone="UTC", row_version=1,
                ),
                Platform(
                    id=platform_id, key="test_platform", name="Test", category="video",
                    enabled=True, adapter_key=ADAPTER_KEY, capabilities={},
                ),
                Account(
                    id=account_id, workspace_id=workspace_id, platform_id=platform_id,
                    external_id="external-guard", display_name="守护账号",
                    source_kind="imported", source_provider="manual",
                    fetched_at=datetime(2026, 7, 1, tzinfo=UTC), sync_status="success",
                ),
            ]
        )
        await s.commit()
        s.add(
            SyncRun(
                id=orphan_id, workspace_id=workspace_id, target_type="account",
                target_id=account_id, adapter_key=ADAPTER_KEY, request_id="req-orphan2",
                queued_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
                started_at=datetime(2026, 7, 25, 12, 5, tzinfo=UTC),
                status="running", lock_key=None, metadata_json={},
            )
        )
        s.add(
            SyncRun(
                id=newer_id, workspace_id=workspace_id, target_type="account",
                target_id=account_id, adapter_key=ADAPTER_KEY, request_id="req-newer",
                queued_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
                started_at=datetime(2026, 8, 2, 12, 5, tzinfo=UTC),
                status="success", finished_at=datetime(2026, 8, 2, 12, 30, tzinfo=UTC),
                lock_key=None, metadata_json={},
            )
        )
        await s.commit()

    settings = _build_settings()
    async with maker() as session:
        recovered = await SyncService(session, registry, settings).recover_stale_runs(
            stale_before=datetime(2026, 8, 1, tzinfo=UTC),
        )
        assert recovered == 1  # only the orphan; the completed run is untouched

    async with maker() as session:
        orphan = await session.get(SyncRun, orphan_id)
        newer = await session.get(SyncRun, newer_id)
        account = await session.get(Account, account_id)
        assert orphan.status == "error"
        assert newer.status == "success"
        assert account.sync_status == "success", (
            "a newer completed run must not be clobbered by stale recovery"
        )
    await engine.dispose()
