"""End-to-end tests for the account synchronization pipeline (#70).

The chain under test is: ``SyncService.request_account_sync`` (dedup + account
lock) -> ``enqueue_platform_sync`` (Celery ``sync_account`` on the ``monitoring``
queue) -> ``PlatformSyncExecutor.execute_account_run`` (adapter round-trip) ->
``sync_run_events`` tracklog.

Everything runs offline against the shared PostgreSQL test database:

* the **broker** is faked — ``sync_account.delay`` is monkeypatched to a
  recorder, so no Redis round-trip and no worker are needed to prove the
  enqueue happened (queue routing is asserted from the Celery router itself);
* the **adapters** are test-only subclasses of ``RealShapedTestAdapter``
  (conftest) that raise the real error classes the sync engine classifies
  (``TransientAdapterError`` = retryable, ``LoginRequiredError`` = terminal).

No ``mock`` source kind, no falsified success, no live platform call.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.adapters.platforms.base import (
    AdapterCallContext,
    PlatformAccountData,
    TransientAdapterError,
)
from app.adapters.platforms.browser_base import LoginRequiredError
from app.core.config import Settings
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun, SyncRunEvent
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import (
    PlatformSyncExecutor,
    RetryableSyncError,
    SyncService,
    enqueue_platform_sync,
)

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL, RealShapedTestAdapter

ADAPTER_KEY = "test_sync_adapter"
PLATFORM_KEY = "test_platform"


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


class TransientFailingAdapter(RealShapedTestAdapter):
    """Profile fetch always fails with the retryable transient error class."""

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        raise TransientAdapterError("simulated upstream 503 while resolving the profile")


class LoginWalledAdapter(RealShapedTestAdapter):
    """Profile fetch hits a login wall / anti-bot check (non-retryable)."""

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        raise LoginRequiredError(PLATFORM_KEY, "登录墙拦截了公开页采集")


async def _seed_account(
    session: AsyncSession,
    workspace_id: UUID,
    platform_id: UUID,
    account_id: UUID,
) -> None:
    """Insert the workspace / platform / account a sync run needs.

    Parents are committed before any ``sync_runs`` row is written because
    PostgreSQL enforces the foreign keys.
    """

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
                key=PLATFORM_KEY,
                name="Test",
                category="video",
                enabled=True,
                adapter_key=ADAPTER_KEY,
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
    await session.commit()


async def _with_session(work: Callable[[AsyncSession], Awaitable[None]]) -> None:
    """Run ``work`` against a freshly built engine, then dispose it.

    Each call owns its engine so the helper is safe inside ``asyncio.run`` —
    asyncpg pools are bound to the loop that created them, and the retry test
    drives several independent loops (one per simulated Celery attempt).

    The schema is *not* (re)created here: the session-scoped ``setup_test_db``
    fixture already built it. Issuing ``create_all`` per call would run DDL
    dozens of times inside one test and deadlock against the autouse TRUNCATE
    of the next one.
    """

    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            await work(session)
    finally:
        await engine.dispose()


async def _events(session: AsyncSession, run_id: UUID) -> list[SyncRunEvent]:
    return list(
        (
            await session.scalars(
                select(SyncRunEvent)
                .where(SyncRunEvent.sync_run_id == run_id)
                .order_by(SyncRunEvent.sequence.asc(), SyncRunEvent.created_at.asc())
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# 1. Dedup: one active run per account lock
# ---------------------------------------------------------------------------


async def test_request_account_sync_dedups_while_a_run_is_active() -> None:
    """A second request while a run holds ``account:{id}`` returns that run.

    The account lock is the only thing preventing two workers from scraping the
    same account concurrently, so the dedup must be keyed on the persisted
    ``lock_key`` — not on a caller-side guard.
    """

    workspace_id, platform_id, account_id = uuid4(), uuid4(), uuid4()

    async def _body(session: AsyncSession) -> None:
        await _seed_account(session, workspace_id, platform_id, account_id)
        service = SyncService(
            session, _build_registry(RealShapedTestAdapter(key=ADAPTER_KEY)), _build_settings()
        )

        first, created_first = await service.request_account_sync(
            workspace_id, account_id, request_id="req-dedup-1"
        )
        second, created_second = await service.request_account_sync(
            workspace_id, account_id, request_id="req-dedup-2"
        )

        assert created_first is True, "the first request must create a run"
        assert created_second is False, "the second request must reuse the active run"
        assert second.id == first.id
        assert second.request_id == "req-dedup-1", "the original run is returned verbatim"

        run = await session.get(SyncRun, first.id)
        assert run is not None
        assert run.lock_key == f"account:{account_id}"
        assert run.status == "queued"

        # Exactly one run row exists for this account.
        runs = list(
            (await session.scalars(select(SyncRun).where(SyncRun.target_id == account_id))).all()
        )
        assert len(runs) == 1

    await _with_session(_body)


# ---------------------------------------------------------------------------
# 2. Enqueue: the queued run is handed to the monitoring queue
# ---------------------------------------------------------------------------


async def test_request_account_sync_enqueues_sync_account_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enqueue_platform_sync`` must dispatch ``sync_account`` for the new run.

    The broker is faked: ``sync_account.delay`` is replaced by a recorder, which
    keeps the assertion on *our* dispatch contract (task + argument + queue)
    instead of on a live Redis. The queue is read back from the Celery router so
    a routing regression (``monitoring`` -> default ``maintenance``) is caught.
    """

    from app.tasks.celery_app import celery_app
    from app.tasks.monitoring import sync_account

    dispatched: list[tuple[str, ...]] = []
    monkeypatch.setattr(sync_account, "delay", lambda *args: dispatched.append(args), raising=True)

    workspace_id, platform_id, account_id = uuid4(), uuid4(), uuid4()

    async def _body(session: AsyncSession) -> None:
        await _seed_account(session, workspace_id, platform_id, account_id)
        service = SyncService(
            session, _build_registry(RealShapedTestAdapter(key=ADAPTER_KEY)), _build_settings()
        )
        run, created = await service.request_account_sync(
            workspace_id, account_id, request_id="req-enqueue"
        )
        assert created is True
        # Mirrors the API route: only a freshly created run is enqueued.
        enqueue_platform_sync(run.id)
        assert dispatched == [(str(run.id),)], "sync_account must be enqueued once with the run id"

    await _with_session(_body)

    assert sync_account.name == "app.tasks.monitoring.sync_account"
    route = celery_app.amqp.router.route({}, sync_account.name)
    queue = route.get("queue")
    assert getattr(queue, "name", queue) == "monitoring"


# ---------------------------------------------------------------------------
# 3a. Failure path: transient adapter error -> retried -> retry_exhausted
# ---------------------------------------------------------------------------


class _FakeRetry(Exception):
    """Stand-in for ``celery.exceptions.Retry`` raised by ``Task.retry``."""


class _FakeTask:
    """Minimal bound-task double for ``_run_with_retry``.

    Celery's real ``Task.retry`` re-queues the message and raises ``Retry``;
    here it just counts the attempt and returns an exception the production
    code raises itself, so the retry ladder can be driven synchronously.
    """

    def __init__(self) -> None:
        self.request = SimpleNamespace(retries=0)
        self.countdowns: list[int] = []

    def retry(self, *, exc: BaseException, countdown: int, max_retries: int) -> BaseException:
        self.request.retries += 1
        self.countdowns.append(countdown)
        return _FakeRetry(str(exc))


def test_transient_adapter_error_retries_then_exhausts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retryable adapter outage is retried, then closed as ``retry_exhausted``.

    This drives the real ``_run_with_retry`` ladder from ``app.tasks.monitoring``
    with the broker/worker replaced by a loop: only the two engine-building
    helpers are redirected at the test database (the production ones would build
    an engine from the *runtime* settings and hit the dev database).

    The test is synchronous on purpose: ``_run_with_retry`` calls
    ``asyncio.run``, which cannot nest inside a running event loop.
    """

    from app.tasks import monitoring as monitoring_tasks

    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    max_retries = 2

    async def _setup(session: AsyncSession) -> None:
        await _seed_account(session, workspace_id, platform_id, account_id)
        session.add(
            SyncRun(
                id=run_id,
                workspace_id=workspace_id,
                target_type="account",
                target_id=account_id,
                adapter_key=ADAPTER_KEY,
                request_id="req-transient",
                queued_at=datetime.now(UTC),
                status="queued",
                lock_key=f"account:{account_id}",
                metadata_json={"trigger": "manual", "retry_count": 0},
            )
        )
        await session.commit()

    asyncio.run(_with_session(_setup))

    async def _fake_effective(settings: Settings) -> int:
        return max_retries

    async def _fake_execute(target: UUID) -> None:
        async def _work(session: AsyncSession) -> None:
            executor = PlatformSyncExecutor(
                session,
                _build_registry(TransientFailingAdapter(key=ADAPTER_KEY)),
                _build_settings(),
            )
            await executor.execute_account_run(target)

        await _with_session(_work)

    async def _fake_mark_exhausted(target: UUID, message: str) -> None:
        async def _work(session: AsyncSession) -> None:
            executor = PlatformSyncExecutor(
                session,
                _build_registry(TransientFailingAdapter(key=ADAPTER_KEY)),
                _build_settings(),
            )
            await executor.mark_retry_exhausted(target, message)

        await _with_session(_work)

    monkeypatch.setattr(monitoring_tasks, "_effective_sync_task_max_retries", _fake_effective)
    monkeypatch.setattr(monitoring_tasks, "_execute", _fake_execute)
    monkeypatch.setattr(monitoring_tasks, "_mark_exhausted", _fake_mark_exhausted)

    task = _FakeTask()
    attempts = 0
    while True:
        attempts += 1
        assert attempts <= max_retries + 2, "retry ladder must terminate"
        try:
            monitoring_tasks._run_with_retry(task, run_id)
        except _FakeRetry:
            continue
        except RetryableSyncError:
            break  # re-raised by the task after the run was closed
        raise AssertionError("a permanently transient adapter must never report success")

    assert attempts == max_retries + 1, "one initial attempt plus the configured retries"
    assert task.request.retries == max_retries
    assert task.countdowns == [1, 2], "exponential backoff between attempts"

    async def _verify(session: AsyncSession) -> None:
        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        assert run is not None and account is not None
        assert run.status == "error"
        assert run.error_code == "retry_exhausted", "the final code must reflect exhaustion"
        assert "simulated upstream 503" in (run.error_message or ""), (
            "the exhaustion message must carry the underlying adapter failure"
        )
        assert run.lock_key is None, "the account lock must be released"
        assert run.finished_at is not None
        assert run.progress_stage == "failed"
        # Every failed attempt (including the last one) bumps the counter.
        assert run.metadata_json.get("retry_count") == max_retries + 1
        assert account.sync_status == "error"
        assert account.last_sync_error_code == "retry_exhausted"

        events = await _events(session, run_id)
        assert events, "the tracklog must record the failed run"
        # Every attempt logs its failed platform round-trip...
        failed_calls = [
            event
            for event in events
            if event.event_type == "external_call" and event.level == "error"
        ]
        assert len(failed_calls) == max_retries + 1
        assert all(
            call.payload.get("error_code") == "transient_provider_error" for call in failed_calls
        )
        assert all(call.payload.get("retryable") is True for call in failed_calls)
        # ...and the terminal close appends the fatal error event.
        errors = [e for e in events if e.event_type == "error" and e.level == "error"]
        assert len(errors) == 1
        assert errors[0].payload.get("code") == "retry_exhausted"

    asyncio.run(_with_session(_verify))


# ---------------------------------------------------------------------------
# 3b. Failure path: login wall -> fail fast, no retry
# ---------------------------------------------------------------------------


async def test_login_required_fails_fast_without_retry() -> None:
    """``LoginRequiredError`` is terminal: no ``RetryableSyncError``, no re-queue.

    A login wall will still be there on the next attempt, so retrying only burns
    worker slots while the account stays locked. The run must close immediately
    with ``login_required`` and release the lock.
    """

    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()

    async def _body(session: AsyncSession) -> None:
        await _seed_account(session, workspace_id, platform_id, account_id)
        session.add(
            SyncRun(
                id=run_id,
                workspace_id=workspace_id,
                target_type="account",
                target_id=account_id,
                adapter_key=ADAPTER_KEY,
                request_id="req-login",
                queued_at=datetime.now(UTC),
                status="queued",
                lock_key=f"account:{account_id}",
                metadata_json={"trigger": "manual", "retry_count": 0},
            )
        )
        await session.commit()

        executor = PlatformSyncExecutor(
            session,
            _build_registry(LoginWalledAdapter(key=ADAPTER_KEY)),
            _build_settings(),
        )
        # Must return normally — a terminal error is handled, never re-raised.
        await executor.execute_account_run(run_id)

        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        assert run is not None and account is not None
        assert run.status == "error"
        assert run.error_code == "login_required"
        assert run.lock_key is None, "a terminal failure must release the account lock"
        assert run.metadata_json.get("retry_count") == 0, "a login wall must not be retried"
        assert run.error_hint, "operators need a remediation hint for a login wall"
        assert account.sync_status == "error"
        assert account.last_sync_error_code == "login_required"

        events = await _events(session, run_id)
        failed_calls = [
            event
            for event in events
            if event.event_type == "external_call" and event.level == "error"
        ]
        assert len(failed_calls) == 1, "exactly one attempt was made"
        assert failed_calls[0].payload.get("retryable") is False

    await _with_session(_body)


# ---------------------------------------------------------------------------
# 4. Tracklog correctness: ordering + an error event on failure
# ---------------------------------------------------------------------------


async def test_sync_run_events_timeline_is_ordered_and_records_the_error() -> None:
    """The tracklog of a failed run must be replayable and end on the error.

    ``get_run_detail`` is what the UI reads, so the assertions run through the
    service: sequences start at 1, increase by exactly 1 (no gaps, nothing
    dropped), and the failure is visible as an ``error``/``error`` event.
    """

    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()

    async def _body(session: AsyncSession) -> None:
        await _seed_account(session, workspace_id, platform_id, account_id)
        session.add(
            SyncRun(
                id=run_id,
                workspace_id=workspace_id,
                target_type="account",
                target_id=account_id,
                adapter_key=ADAPTER_KEY,
                request_id="req-timeline",
                queued_at=datetime.now(UTC),
                status="queued",
                lock_key=f"account:{account_id}",
                metadata_json={},
            )
        )
        await session.commit()

        registry = _build_registry(LoginWalledAdapter(key=ADAPTER_KEY))
        settings = _build_settings()
        await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

        detail = await SyncService(session, registry, settings).get_run_detail(
            workspace_id, account_id, run_id
        )
        assert detail.run.id == run_id
        assert detail.run.status == "error"

        sequences = [event.sequence for event in detail.events]
        assert sequences, "a failed run must still produce a timeline"
        assert sequences == sorted(sequences), "events must be returned in sequence order"
        assert sequences == list(range(1, len(sequences) + 1)), "sequence must be gapless from 1"

        timestamps = [event.created_at for event in detail.events]
        assert timestamps == sorted(timestamps), "sequence order must match chronological order"

        error_events = [
            event
            for event in detail.events
            if event.event_type == "error" and event.level == "error"
        ]
        assert len(error_events) == 1, "a failed run must expose exactly one fatal error event"
        assert error_events[0].sequence == sequences[-1], "the fatal error closes the timeline"
        assert error_events[0].payload.get("code") == "login_required"
        assert "login_required" in (error_events[0].payload.get("error_detail") or "") or (
            error_events[0].message
        ), "the error event must carry a diagnosable message"

        # Every event carries the step timing the detail page renders.
        assert all("elapsed_ms" in event.payload for event in detail.events)

    await _with_session(_body)
