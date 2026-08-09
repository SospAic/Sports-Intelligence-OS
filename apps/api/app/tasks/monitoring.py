import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session
from app.models.download import Download
from app.models.monitoring import Account, ContentItem, Platform
from app.models.settings import RuntimeSettingOverride
from app.repositories.sync import SyncRepository
from app.services.monitoring import MonitoringService
from app.services.platform_credentials import PlatformCredentialService
from app.services.platform_detect import detect_platform_key_from_url
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


async def _mark_crashed(run_id: UUID, message: str) -> None:
    """Close a run whose task raised something the engine did not expect.

    Uses its own engine/session so it still works when the run's original
    session was left unusable by the failure.
    """

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).mark_unexpected_failure(
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
    except Exception as exc:  # noqa: BLE001 - last-resort lock release
        # Anything the engine did not classify (a DB constraint violation, a
        # driver error, an adapter bug) must still close the run and release the
        # account lock. Leaving the row in ``running`` would make the account
        # look permanently "syncing" and reject every later sync request until
        # the periodic stale sweep fires minutes later.
        logger.exception("sync run %s crashed with an unhandled error", run_id)
        try:
            asyncio.run(_mark_crashed(run_id, f"{type(exc).__name__}: {exc}"))
        except Exception:  # noqa: BLE001 - never mask the original failure
            logger.exception("failed to release sync run %s after a crash", run_id)
        raise


async def _effective_sync_task_max_retries(settings: Settings) -> int:
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
    return asyncio.run(_run_collect_comments(UUID(content_id)))


async def _run_collect_comments(content_id: UUID) -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            service = MonitoringService(session)
            return await service.collect_content_comments(content_id)
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.download_url"
)
def download_url_task(self: Task, download_id: str) -> None:
    """Fetch a submitted URL with yt-dlp and store the resulting media."""
    asyncio.run(_run_download(UUID(download_id)))


async def _run_download(download_id: UUID) -> None:
    from app.adapters.platforms.yt_dlp import YtDlpAdapter
    from app.services.download import DownloadService, explain_empty_download

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
            sync_config = await SyncRepository(session).get_sync_settings_config(
                download.workspace_id
            )
            yt_config = sync_config.get("yt_dlp")
            detected_platform = detect_platform_key_from_url(download.url)
            if detected_platform:
                _, platform_config = await PlatformCredentialService(session, settings).resolve(
                    download.workspace_id, detected_platform
                )
                yt_config = {
                    **platform_config,
                    **(yt_config if isinstance(yt_config, dict) else {}),
                }
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
                structured=yt_config if isinstance(yt_config, dict) else None,
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
            if media and options.get("save_to_works") and entries:
                await _save_download_as_work(session, download, entries[0], media)
            empty_reason = None if media else explain_empty_download(dict(options), entries)
            await service.mark_done(download_id, media, platform, empty_reason)
    except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
        logger.warning("download %s failed: %s", download_id, exc)
        async with session_factory() as session:
            await DownloadService(session).mark_failed(download_id, str(exc))
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.preview_download"
)
def preview_download_task(self: Task, url: str, workspace_id: str) -> dict:
    """Parse a video URL with yt-dlp for the download preview card.

    Mirrors ``download_url_task`` but only extracts metadata (no media save),
    and returns a JSON-serializable result dict the API polls for.
    """

    return asyncio.run(_run_preview(url, UUID(workspace_id)))


async def _run_preview(url: str, workspace_id: UUID) -> dict:
    from app.services.download import UNRESOLVABLE_URL_DETAIL, build_download_preview

    settings = get_settings()
    try:
        return await build_download_preview(url, workspace_id, settings)
    except Exception as exc:  # noqa: BLE001 - surface a safe error to the poll
        logger.warning("preview_download_task failed for %s: %s", url, exc)
        return {
            "status": "error",
            "error_code": 422,
            "error_detail": UNRESOLVABLE_URL_DETAIL,
        }


async def _save_download_as_work(
    session: AsyncSession,
    download: Download,
    entry: dict[str, object],
    media: dict[str, object],
) -> None:
    # A download can be attached to the works list only when it belongs to an
    # already monitored account. This avoids creating orphan records with no
    # ownership or platform context.
    extractor = str(entry.get("extractor") or entry.get("ie_key") or "").casefold()
    platform_key = next(
        (
            key
            for key, names in {
                "youtube": ("youtube",),
                "tiktok": ("tiktok",),
                "douyin": ("douyin",),
                "bilibili": ("bilibili",),
            }.items()
            if any(name in extractor for name in names)
        ),
        None,
    )
    external_id = str(entry.get("id") or "").strip()
    if not platform_key or not external_id:
        return
    platform = await session.scalar(select(Platform).where(Platform.key == platform_key))
    if platform is None:
        return
    identity_candidates = {
        str(value).lstrip("@")
        for value in (
            entry.get("channel_id"),
            entry.get("uploader_id"),
            entry.get("uploader"),
        )
        if value
    }
    if not identity_candidates:
        return
    account = await session.scalar(
        select(Account).where(
            Account.workspace_id == download.workspace_id,
            Account.platform_id == platform.id,
            Account.external_id.in_(identity_candidates),
        )
    )
    if account is None:
        return
    existing = await session.scalar(
        select(ContentItem).where(
            ContentItem.workspace_id == download.workspace_id,
            ContentItem.account_id == account.id,
            ContentItem.external_id == external_id,
        )
    )
    if existing is not None:
        existing.media = media
        return
    now = datetime.now(UTC)
    published_at = None
    if entry.get("timestamp") is not None:
        try:
            published_at = datetime.fromtimestamp(float(entry["timestamp"]), tz=UTC)
        except (TypeError, ValueError, OSError):
            published_at = None
    session.add(
        ContentItem(
            workspace_id=download.workspace_id,
            platform_id=platform.id,
            account_id=account.id,
            external_id=external_id,
            content_type="video",
            title=str(entry.get("title") or external_id)[:500],
            description=str(entry.get("description")) if entry.get("description") else None,
            published_at=published_at,
            duration_seconds=entry.get("duration"),
            canonical_url=download.url,
            cover_url=str(entry.get("thumbnail")) if entry.get("thumbnail") else None,
            language=None,
            status="published",
            metadata_json={"saved_from_download": True},
            first_seen_at=now,
            last_seen_at=now,
            source_kind="live",
            source_provider="yt_dlp",
            fetched_at=now,
            source_url=download.url,
            media=media,
            tags=[],
        )
    )
    await session.commit()


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
                datetime.now(UTC) - timedelta(seconds=settings.sync_stale_after_seconds),
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
            service = SyncService(session, build_platform_adapter_registry(settings), settings)
            # Use the sync-specific threshold (run budget + grace), not the
            # generic 35-minute task lease: a crashed account sync must free its
            # lock in minutes, otherwise the account is unsyncable until then.
            return await service.recover_stale_runs(
                datetime.now(UTC) - timedelta(seconds=settings.sync_stale_after_seconds),
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
