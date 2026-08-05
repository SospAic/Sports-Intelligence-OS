import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from celery import Task
from sqlalchemy import select

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.settings import RuntimeSettingOverride
from app.services.sync import (
    PlatformSyncExecutor,
    RetryableSyncError,
    SyncService,
    SyncValidationError,
)
from app.services.monitoring import MonitoringService
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
    # Effective retry cap: a runtime override (if set) wins over the frozen
    # environment default, so changing it on the Sync panel takes effect
    # immediately without restarting the worker.
    effective = asyncio.run(_effective_sync_task_max_retries(settings))
    try:
        asyncio.run(_execute(run_id))
    except RetryableSyncError as exc:
        retries = int(task.request.retries)
        if retries >= effective:
            asyncio.run(_mark_exhausted(run_id, str(exc)))
            raise
        raise task.retry(
            exc=exc,
            countdown=min(2**retries, 60),
            max_retries=effective,
        ) from exc


async def _effective_sync_task_max_retries(settings) -> int:
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            row = await session.scalar(
                select(RuntimeSettingOverride).where(
                    RuntimeSettingOverride.key == "sync_task_max_retries"
                )
            )
            if row is not None and isinstance(row.value_json, int):
                return max(0, min(10, row.value_json))
    finally:
        await engine.dispose()
    return int(settings.sync_task_max_retries)


@celery_app.task(bind=True, name="app.tasks.monitoring.sync_account")  # type: ignore[untyped-decorator]
def sync_account(self: Task, run_id: str) -> None:
    _run_with_retry(self, UUID(run_id))


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.collect_content_comments"
)
def collect_content_comments(self: Task, content_id: str) -> int:
    """Best-effort fetch & store of a content item's comments (yt-dlp backed)."""
    return _run_collect_comments(UUID(content_id))


async def _run_collect_comments(content_id: UUID) -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            service = MonitoringService(session, get_settings())
            return await service.collect_content_comments(content_id)
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.download_url"
)
def download_url_task(self: Task, download_id: str) -> None:
    """Fetch a submitted URL with yt-dlp and store the resulting media."""
    _run_download(UUID(download_id))


async def _run_download(download_id: UUID) -> None:
    from app.adapters.platforms.yt_dlp import YtDlpAdapter
    from app.services.download import DownloadService

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    media_root = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")
    try:
        async with session_factory() as session:
            service = DownloadService(session)
            download = await service.get(download_id)
            if download is None:
                return
            await service.mark_running(download_id)
            options = download.options or {}
            media_dir = os.path.join(
                media_root, str(download.workspace_id), "downloads", str(download_id)
            )
            os.makedirs(media_dir, exist_ok=True)
            adapter = YtDlpAdapter()
            entries, _ = await adapter._run_yt_dlp(
                download.url,
                download={
                    "download_video": options.get("download_video", True),
                    "video_quality": options.get("video_quality", "best"),
                    "video_format": options.get("video_format", "best"),
                    "audio_format": options.get("audio_format", "best"),
                    "bitrate": options.get("bitrate", ""),
                    "naming_rule": options.get("naming_rule", "id"),
                    "write_subtitles": options.get("write_subtitles", True),
                    "write_auto_subtitles": options.get("write_auto_subtitles", False),
                    "subtitle_langs": options.get("subtitle_langs", "zh.*,en.*"),
                    "write_thumbnail": options.get("write_thumbnail", True),
                    "write_info_json": options.get("write_info_json", False),
                },
                media_dir=media_dir,
                playlist_end=1,
            )
            media = None
            platform = None
            for entry in entries:
                vid = entry.get("id")
                if not vid:
                    continue
                collected = YtDlpAdapter._collect_media(media_root, media_dir, vid)
                if collected:
                    media = collected
                    platform = entry.get("extractor") or entry.get("ie_key")
                    break
            await service.mark_done(download_id, media, platform)
    except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
        logger.warning("download %s failed: %s", download_id, exc)
        async with session_factory() as session:
            await DownloadService(session).mark_failed(download_id, str(exc))
    finally:
        await engine.dispose()


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
