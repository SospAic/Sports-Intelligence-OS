"""Tests for user-initiated cancellation of account sync runs.

These tests verify the *decision and audit* logic of cancelling a queued/running
sync run: the run is marked ``cancelled``, the account lock is released, and an
already-terminal run is left untouched (idempotent). They use the shared
PostgreSQL test database (``sports_intelligence_test``) — no live platform calls.

Per the project's no-fake-success rule, cancellation only records intent against
the persisted run; it never asserts a successful platform call.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import (
    SyncNotFoundError,
    SyncService,
    SyncValidationError,
    cancel_sync_run,
)

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL


def _build_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )


def _build_registry() -> ProviderRegistry:
    return ProviderRegistry()


async def _seed(
    session: object,
    workspace_id: object,
    platform_id: object,
    account_id: object,
    run_id: object,
    *,
    run_status: str = "queued",
    lock_key: str | None = "account:acct",
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
                adapter_key="test_adapter",
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
                sync_status="never",
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
            adapter_key="test_adapter",
            request_id="req-cancel",
            queued_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
            status=run_status,
            lock_key=lock_key,
            metadata_json={},
        )
    )
    await s.commit()


async def test_cancel_queued_run_marks_cancelled_and_releases_lock() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id)

    async with maker() as session:
        result = await cancel_sync_run(session, workspace_id, run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        assert run.status == "cancelled"
        assert run.lock_key is None
        assert run.finished_at is not None
        assert run.progress_stage == "cancelled"
        assert account.sync_status == "cancelled"
        assert result.status == "cancelled"
    await engine.dispose()


async def test_cancel_running_run_marks_cancelled() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, run_status="running")

    async with maker() as session:
        await cancel_sync_run(session, workspace_id, run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        assert run.status == "cancelled"
        assert run.lock_key is None
    await engine.dispose()


async def test_cancel_terminal_run_is_idempotent() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, run_status="success")

    async with maker() as session:
        result = await cancel_sync_run(session, workspace_id, run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        assert run.status == "success", "terminal run must not be mutated"
        assert result.status == "success"
    await engine.dispose()


async def test_cancel_missing_workspace_raises_not_found() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id)

    async with maker() as session:
        try:
            await cancel_sync_run(session, uuid4(), run_id)
            raise AssertionError("expected SyncNotFoundError")
        except SyncNotFoundError:
            pass
    await engine.dispose()


async def test_service_cancel_rejects_run_not_belonging_to_account() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    other_account_id = uuid4()
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id)
        # A real second account in the same workspace — exists, but is not the
        # run's target. The cancel must be rejected with SyncValidationError.
        session.add(
            Account(
                id=other_account_id,
                workspace_id=workspace_id,
                platform_id=platform_id,
                external_id="external-002",
                display_name="其它账号",
                source_kind="imported",
                source_provider="manual",
                sync_status="never",
                fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    async with maker() as session:
        service = SyncService(session, _build_registry(), _build_settings())
        try:
            await service.cancel_sync_run(workspace_id, other_account_id, run_id)
            raise AssertionError("expected SyncValidationError")
        except SyncValidationError:
            pass
    await engine.dispose()


async def test_executor_skips_already_cancelled_run() -> None:
    """If a run was cancelled before a worker picked it up, execute_account_run
    must early-exit and must not flip the account into 'syncing'."""
    from app.services.sync import PlatformSyncExecutor

    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with maker() as session:
        await _seed(
            session,
            workspace_id,
            platform_id,
            account_id,
            run_id,
            run_status="cancelled",
            lock_key=None,
        )

    async with maker() as session:
        await PlatformSyncExecutor(
            session, _build_registry(), _build_settings()
        ).execute_account_run(run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        assert run.status == "cancelled", "cancelled run must not be executed"
        assert account.sync_status == "never", "account must not enter 'syncing'"
    await engine.dispose()
