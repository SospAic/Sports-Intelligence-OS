"""Regression tests for the "an account sync can never stall" guarantees.

Account monitoring is the product's core loop, so a sync run must always reach
a terminal state and always release its account lock. Three real production
failures motivated these tests:

1. A tracklog event was emitted with ``event_type="account_profile"``, which is
   not in the ``ck_sync_run_events_sync_run_event_type`` CHECK constraint. The
   flush raised ``CheckViolationError`` -> the session became unusable
   (``PendingRollbackError``) -> the Celery task died with an exception the
   engine did not classify -> the run stayed ``running`` with its ``lock_key``
   held. The account then looked permanently "syncing" and every later sync
   request was rejected.
2. Nothing closed a run when the task raised an *unexpected* exception; only
   ``RetryableSyncError`` was handled.
3. The stale-run watchdog used the generic 2100s task lease, so even after the
   run budget was lowered to 300s a crashed run held its lock for 35 minutes.
4. A retry dispatched after the run's absolute deadline computed a *negative*
   remaining budget, so ``asyncio.wait_for`` fired before the adapter was even
   called; the instant timeout looked transient and the run was re-queued in a
   loop while still holding the account lock.

The fixes are, respectively: normalize unknown event types, a last-resort
terminal-failure path (``mark_unexpected_failure``), a sync-specific stale
threshold derived from the run budget, and refusing to start an attempt that
has no budget left (``sync_budget_exhausted``).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun, SyncRunEvent
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import (
    PlatformSyncExecutor,
    SyncService,
    _normalize_event_type,
)

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL, RealShapedTestAdapter

ADAPTER_KEY = "test_stall_guard_adapter"


def _build_settings(**overrides: object) -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
        **overrides,  # type: ignore[arg-type]
    )


async def _seed(
    session,
    workspace_id,
    platform_id,
    account_id,
    run_id,
    *,
    status="running",
    age_seconds: int = 900,
    already_started: bool = True,
):
    session.add_all(
        [
            Workspace(
                id=workspace_id,
                name="ws",
                slug=f"ws-{str(workspace_id)[:8]}",
                status="active",
                default_timezone="UTC",
                row_version=1,
            ),
            Platform(
                id=platform_id,
                key=f"stall_platform_{str(platform_id)[:8]}",
                name="Stall",
                category="video",
                enabled=True,
                adapter_key=ADAPTER_KEY,
                capabilities={},
            ),
            Account(
                id=account_id,
                workspace_id=workspace_id,
                platform_id=platform_id,
                external_id="external-stall-001",
                display_name="测试账号",
                source_kind="imported",
                source_provider="manual",
                fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ]
    )
    await session.commit()
    started = datetime.now(UTC) - timedelta(seconds=age_seconds)
    session.add(
        SyncRun(
            id=run_id,
            workspace_id=workspace_id,
            target_type="account",
            target_id=account_id,
            adapter_key=ADAPTER_KEY,
            request_id=f"req-{str(run_id)[:8]}",
            queued_at=started,
            started_at=started if already_started else None,
            status=status,
            lock_key=f"account:{account_id}",
            progress_stage="account_profile",
            metadata_json={"heartbeat_at": started.isoformat()},
        )
    )
    await session.commit()
    return started


# ---------------------------------------------------------------------------
# 1. Unknown tracklog event types must never violate the CHECK constraint
# ---------------------------------------------------------------------------


def test_normalize_event_type_passes_known_values_through() -> None:
    for known in (
        "stage",
        "page",
        "item",
        "analytics",
        "external_call",
        "warning",
        "error",
        "info",
        "summary",
    ):
        assert _normalize_event_type(known, "info") == known


def test_normalize_event_type_buckets_unknown_values_by_level() -> None:
    # The real regression: a stage name leaked into the event_type slot.
    assert _normalize_event_type("account_profile", "warn") == "warning"
    assert _normalize_event_type("account_profile", "error") == "error"
    assert _normalize_event_type("account_profile", "info") == "info"
    assert _normalize_event_type("", "debug") == "info"


async def test_emit_with_unknown_event_type_is_persisted_not_rejected() -> None:
    """``_emit`` must survive an unsupported event type.

    Persisting it verbatim raises CheckViolationError and poisons the session,
    which is what left runs stuck in ``running``. The event must still be
    written (diagnostics are never silently dropped) under a legal type, with
    the original value preserved in the payload.
    """
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id)
            run = await session.get(SyncRun, run_id)
            assert run is not None
            executor = PlatformSyncExecutor(session, ProviderRegistry(), _build_settings())
            executor._event_seq = 0
            executor._emit(
                run,
                "account_profile",  # not a legal event_type
                "warn",
                "抓取到的显示名无效（的抖音），已跳过更新以免污染账号名",
                {"raw_display_name": "的抖音"},
            )
            # The flush must succeed — this is the whole point.
            await session.commit()

            events = list(
                (
                    await session.scalars(
                        select(SyncRunEvent).where(SyncRunEvent.sync_run_id == run_id)
                    )
                ).all()
            )
            assert len(events) == 1
            assert events[0].event_type == "warning"
            assert events[0].level == "warn"
            assert events[0].payload["requested_event_type"] == "account_profile"
            # And the session is still usable afterwards.
            assert await session.scalar(select(SyncRun.id).where(SyncRun.id == run_id)) == run_id
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 2. An unexpected crash must still close the run and release the lock
# ---------------------------------------------------------------------------


async def test_mark_unexpected_failure_closes_run_and_releases_lock() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id)
            executor = PlatformSyncExecutor(session, ProviderRegistry(), _build_settings())
            await executor.mark_unexpected_failure(run_id, "CheckViolationError: boom")
            await session.commit()

            run = await session.get(SyncRun, run_id)
            assert run is not None
            assert run.status == "error"
            assert run.error_code == "internal_error"
            assert run.finished_at is not None
            # The lock release is what makes the account syncable again.
            assert run.lock_key is None
    finally:
        await engine.dispose()


async def test_mark_unexpected_failure_never_overwrites_a_finished_run() -> None:
    """A late crash handler must not clobber an already-successful run."""
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id, status="success")
            executor = PlatformSyncExecutor(session, ProviderRegistry(), _build_settings())
            await executor.mark_unexpected_failure(run_id, "late crash")
            await session.commit()

            run = await session.get(SyncRun, run_id)
            assert run is not None
            assert run.status == "success"
            assert run.error_code is None
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 3. The stale watchdog must track the run budget, not the 35-minute lease
# ---------------------------------------------------------------------------


def test_sync_stale_threshold_is_derived_from_the_run_budget() -> None:
    settings = _build_settings(sync_run_timeout_seconds=300, sync_stale_grace_seconds=120)
    assert settings.sync_stale_after_seconds == 420
    # Never longer than the generic task lease.
    assert settings.sync_stale_after_seconds <= settings.task_stale_after_seconds


def test_sync_stale_threshold_is_capped_by_the_generic_task_lease() -> None:
    settings = _build_settings(
        sync_run_timeout_seconds=7200,
        sync_stale_grace_seconds=1800,
        task_stale_after_seconds=2100,
    )
    assert settings.sync_stale_after_seconds == 2100


async def test_recover_stale_runs_reaps_a_crashed_run_within_the_budget_window() -> None:
    """A ``running`` run silent for 900s must be released at the 420s threshold.

    With the previous 2100s lease this run would still be holding its account
    lock — the account would be unsyncable for another 20 minutes.
    """
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id)
            settings = _build_settings(sync_run_timeout_seconds=300, sync_stale_grace_seconds=120)
            service = SyncService(session, ProviderRegistry(), settings)
            now = datetime.now(UTC)

            recovered = await service.recover_stale_runs(
                now - timedelta(seconds=settings.sync_stale_after_seconds),
                now - timedelta(seconds=settings.task_dispatch_timeout_seconds),
            )
            assert recovered == 1

            run = await session.get(SyncRun, run_id)
            assert run is not None
            assert run.status == "error"
            assert run.lock_key is None
    finally:
        await engine.dispose()


async def test_recover_stale_runs_leaves_a_healthy_in_flight_run_alone() -> None:
    """A run that heartbeat-ed recently is still working and must be untouched."""
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with maker() as session:
            await _seed(session, workspace_id, platform_id, account_id, run_id)
            run = await session.get(SyncRun, run_id)
            assert run is not None
            run.metadata_json = {"heartbeat_at": datetime.now(UTC).isoformat()}
            await session.commit()

            settings = _build_settings(sync_run_timeout_seconds=300, sync_stale_grace_seconds=120)
            service = SyncService(session, ProviderRegistry(), settings)
            now = datetime.now(UTC)
            recovered = await service.recover_stale_runs(
                now - timedelta(seconds=settings.sync_stale_after_seconds),
                now - timedelta(seconds=settings.task_dispatch_timeout_seconds),
            )
            assert recovered == 0

            run = await session.get(SyncRun, run_id)
            assert run is not None
            assert run.status == "running"
            assert run.lock_key is not None
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 4. An attempt that starts past the run deadline must not run on a negative
#    budget
# ---------------------------------------------------------------------------
#
# Observed in production during a 4-platform concurrency test:
#
#   RetryableSyncError('account profile fetch exceeded -3341s budget')
#
# ``started_at`` is deliberately preserved across retries, so the run budget is
# an *absolute* deadline. When a retry reached the worker long after that
# deadline (queue backlog behind slow browser syncs), the remaining budget went
# negative, ``asyncio.wait_for(..., timeout=-3341)`` fired before the adapter
# was ever called, the instant timeout was classified as a transient outage,
# and the run was re-queued — a crash/retry loop holding the account lock.


class _NeverCalledAdapter(RealShapedTestAdapter):
    """Fails loudly if the sync engine reaches the platform call."""

    def __init__(self) -> None:
        super().__init__(key=ADAPTER_KEY)
        self.resolve_calls = 0

    async def resolve_account(self, ctx, locator):  # type: ignore[no-untyped-def]
        self.resolve_calls += 1
        return await super().resolve_account(ctx, locator)


def _registry_with(adapter: object) -> ProviderRegistry:
    registry: ProviderRegistry = ProviderRegistry()
    registry.register(adapter)  # type: ignore[arg-type]
    return registry


async def test_attempt_past_the_run_deadline_is_closed_not_retried() -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    adapter = _NeverCalledAdapter()
    try:
        async with maker() as session:
            # started_at 900s ago against a 300s budget => -600s remaining.
            await _seed(session, workspace_id, platform_id, account_id, run_id, status="queued")
            settings = _build_settings(sync_run_timeout_seconds=300)
            await PlatformSyncExecutor(
                session, _registry_with(adapter), settings
            ).execute_account_run(run_id)

            run = await session.get(SyncRun, run_id)
            account = await session.get(Account, account_id)
            assert run is not None and account is not None
            # Terminal, not re-queued: the retry loop must end here.
            assert run.status == "error"
            assert run.error_code == "sync_budget_exhausted"
            assert run.lock_key is None, "the account lock must be released"
            assert account.sync_status == "error"
            assert "预算" in (run.error_message or "")
            # And crucially: no platform call was attempted on a negative budget.
            assert adapter.resolve_calls == 0
    finally:
        await engine.dispose()


async def test_first_attempt_after_a_long_queue_wait_still_gets_the_full_budget() -> None:
    """Only *elapsed execution* consumes the budget, never queue waiting time.

    A run can sit in the broker for a long time when the queue is backed up.
    Because ``started_at`` is stamped when the worker picks it up, that wait
    must not count against the run — otherwise a backlog would fail every
    account without a single platform call.
    """
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    adapter = _NeverCalledAdapter()
    try:
        async with maker() as session:
            # Queued 30 minutes ago but never started: full budget on pickup.
            await _seed(
                session,
                workspace_id,
                platform_id,
                account_id,
                run_id,
                status="queued",
                age_seconds=1800,
                already_started=False,
            )
            settings = _build_settings(sync_run_timeout_seconds=300)
            await PlatformSyncExecutor(
                session, _registry_with(adapter), settings
            ).execute_account_run(run_id)

            run = await session.get(SyncRun, run_id)
            assert run is not None
            assert run.error_code != "sync_budget_exhausted"
            assert run.status in ("success", "degraded"), run.error_message
            assert adapter.resolve_calls == 1
    finally:
        await engine.dispose()
