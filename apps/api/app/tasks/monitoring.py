import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from celery import Task

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.services.sync import (
    PlatformSyncExecutor,
    RetryableSyncError,
    SyncService,
    SyncValidationError,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _execute(run_id: UUID) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)
    finally:
        for adapter in registry.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


async def _mark_exhausted(run_id: UUID, message: str) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).mark_retry_exhausted(
                run_id, message
            )
    finally:
        for adapter in registry.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


def _run_with_retry(task: Task, run_id: UUID) -> None:
    settings = get_settings()
    try:
        asyncio.run(_execute(run_id))
    except RetryableSyncError as exc:
        retries = int(task.request.retries)
        if retries >= settings.sync_task_max_retries:
            asyncio.run(_mark_exhausted(run_id, str(exc)))
            raise
        raise task.retry(
            exc=exc,
            countdown=min(2**retries, 60),
            max_retries=settings.sync_task_max_retries,
        ) from exc


@celery_app.task(bind=True, name="app.tasks.monitoring.sync_account")  # type: ignore[untyped-decorator]
def sync_account(self: Task, run_id: str) -> None:
    _run_with_retry(self, UUID(run_id))


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.sync_account_contents"
)
def sync_account_contents(self: Task, run_id: str) -> None:
    """Explicit entry point; P04 executes the same atomic account synchronization workflow."""

    _run_with_retry(self, UUID(run_id))


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.sync_content_metrics"
)
def sync_content_metrics(self: Task, run_id: str) -> None:
    """Explicit entry point; metrics remain transactionally tied to discovered content."""

    _run_with_retry(self, UUID(run_id))


async def _schedule_due() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    run_ids: list[UUID] = []
    try:
        async with session_factory() as session:
            service = SyncService(session, registry, settings)
            await service.recover_stale_runs(
                datetime.now(UTC) - timedelta(seconds=settings.task_stale_after_seconds),
                datetime.now(UTC) - timedelta(seconds=settings.task_dispatch_timeout_seconds),
            )
            accounts = await service.repository.due_accounts(service.settings_now(), limit=500)
            for account in accounts:
                try:
                    run, created = await service.request_account_sync(
                        account.workspace_id,
                        account.id,
                        request_id=f"scheduled-{uuid4()}",
                    )
                except SyncValidationError as exc:
                    # Skeleton adapters or disabled accounts: log and skip;
                    # do not let a single bad account crash the whole batch.
                    logger.info(
                        "scheduled_sync_skipped",
                        extra={
                            "event": "platform.sync.skipped",
                            "account_id": str(account.id),
                            "reason": str(exc),
                        },
                    )
                    continue
                if created:
                    run_ids.append(run.id)
    finally:
        for adapter in registry.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()
    for run_id in run_ids:
        sync_account.delay(str(run_id))
    return len(run_ids)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.monitoring.sync_all_due_accounts"
)
def sync_all_due_accounts() -> int:
    return asyncio.run(_schedule_due())


async def _recover_stale() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            service = SyncService(
                session, build_platform_adapter_registry(settings), settings
            )
            return await service.recover_stale_runs(
                datetime.now(UTC) - timedelta(seconds=settings.task_stale_after_seconds),
                datetime.now(UTC) - timedelta(seconds=settings.task_dispatch_timeout_seconds),
            )
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.monitoring.recover_stale_sync_runs"
)
def recover_stale_sync_runs() -> int:
    """Dedicated high-frequency recovery sweep for stuck sync locks.

    Runs every 60s on the maintenance queue. The fast dispatch-timeout branch
    releases accounts that were queued but never picked up by a worker, so a
    broker/worker outage cannot permanently lock an account.
    """

    return asyncio.run(_recover_stale())


async def _calculate(account_id: UUID) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).calculate_account_metrics(
                account_id
            )
    finally:
        for adapter in registry.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.monitoring.calculate_derived_metrics"
)
def calculate_derived_metrics(account_id: str) -> None:
    asyncio.run(_calculate(UUID(account_id)))
