import asyncio
import json
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from typing import Any
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
from app.services.artifact_registry import reconcile_manifest
from app.services.download import DownloadService
from app.services.monitoring import MonitoringService
from app.services.platform_credentials import PlatformCredentialService
from app.services.platform_detect import detect_platform_key_from_url
from app.services.sync import (
    PlatformSyncExecutor,
    RetryableSyncError,
    SyncService,
    SyncValidationError,
    merge_media_manifest,
)
from app.services.sync_lease import SyncConcurrencyLease, SyncLeaseUnavailable
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _subtitle_language_filter(options: dict[str, object]) -> str:
    """Resolve the two-track UI selection into yt-dlp's language filter.

    ``subtitle_langs`` remains the compatibility path for sync settings and
    older API clients. The detail-page downloader sends the two explicit
    fields, where an empty/``none`` secondary language intentionally means
    single-language output.
    """

    primary = str(options.get("subtitle_primary_lang") or "").strip()
    secondary = str(options.get("subtitle_secondary_lang") or "").strip()
    if primary or secondary:
        selected = [primary]
        if secondary and secondary.casefold() not in {"none", "无", "null"}:
            selected.append(secondary)
        # A language selector represents a language family, not only the
        # bare track id. ``en.*`` also catches en-US/en-GB and the regional
        # variants emitted by YouTube and TikTok.
        return ",".join(
            item if "*" in item else f"{item}.*"
            for item in selected
            if item
        )
    return str(options.get("subtitle_langs") or "zh.*,en.*").strip()


def _subtitle_language_matches(language: object, selector: object) -> bool:
    """Match a returned YouTube language against the UI language family filter."""

    actual = str(language or "").strip().casefold()
    requested = str(selector or "").strip()
    if not actual:
        return False
    if not requested:
        return True
    for raw in requested.split(","):
        token = raw.strip().casefold()
        if not token or token in {"all", "*"}:
            return True
        if token.endswith(".*"):
            family = token[:-2].rstrip("-_.")
            if (
                actual == family
                or actual.startswith(f"{family}-")
                or actual.startswith(f"{family}_")
            ):
                return True
        elif actual == token:
            return True
    return False


def _has_matching_subtitle_track(entry: dict[str, object], key: str, selector: str) -> bool:
    tracks = entry.get(key)
    return isinstance(tracks, dict) and any(
        _subtitle_language_matches(language, selector) for language in tracks
    )


def _yt_dlp_session_configured(config: object) -> bool:
    """Return whether yt-dlp can receive an actual browser/session cookie source."""

    if not isinstance(config, dict):
        return False
    return bool(config.get("cookies_netscape") or config.get("cookies_from_browser"))


class _DownloadProgressSink:
    """Persist yt-dlp stderr in small asynchronous batches.

    yt-dlp invokes its stderr callback from the worker event loop. Database
    writes therefore happen in short-lived sessions scheduled on that same
    loop, keeping the download process non-blocking and avoiding concurrent
    use of the task's main SQLAlchemy session.
    """

    def __init__(self, download_id: UUID, session_factory: Any) -> None:
        self.download_id = download_id
        self.session_factory = session_factory
        self.lines: list[str] = []
        self.task: asyncio.Task[None] | None = None
        self.last_flush = 0.0

    def __call__(self, line: str) -> None:
        self.lines.extend(part.strip() for part in line.splitlines() if part.strip())
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self.task is None or self.task.done():
            if now - self.last_flush >= 0.7:
                self.last_flush = now
                self.task = loop.create_task(self._flush())

    async def _flush(self) -> None:
        lines, self.lines = self.lines, []
        if not lines:
            return
        from app.services.download import DownloadService

        async with self.session_factory() as session:
            await DownloadService(session).append_progress(self.download_id, lines)

    async def close(self) -> None:
        if self.task is not None:
            await self.task
            self.task = None
        if self.lines:
            await self._flush()


async def _execute(run_id: UUID) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    lease: SyncConcurrencyLease | None = None
    try:
        async with session_factory() as session:
            run = await SyncRepository(session).get_run(run_id)
            account = (
                await SyncRepository(session).get_account_unscoped(run.target_id)
                if run is not None
                else None
            )
            platform_key = (
                account.platform.key
                if account is not None
                else str(run.adapter_key).split("_", 1)[0]
                if run is not None
                else "unknown"
            )
            lease = SyncConcurrencyLease(settings)
            handle = await lease.acquire(run_id, platform_key)
            if run is not None:
                run.metadata_json = {
                    **dict(run.metadata_json or {}),
                    "sync_lease": {
                        "platform": handle.platform_key,
                        "global_slot": handle.global_slot,
                        "platform_slot": handle.platform_slot,
                        "waited_seconds": handle.waited_seconds,
                    },
                }
                await session.commit()
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)
    finally:
        if lease is not None:
            await lease.release()
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
    except SyncLeaseUnavailable as exc:
        retries = int(task.request.retries)
        if retries >= effective:
            asyncio.run(_mark_exhausted(run_id, str(exc)))
            raise
        raise task.retry(
            exc=exc,
            countdown=min(2**retries, 60),
            max_retries=effective,
        ) from exc
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
            row = await session.execute(
                select(ContentItem, Account, Platform)
                .join(Account, Account.id == ContentItem.account_id)
                .join(Platform, Platform.id == ContentItem.platform_id)
                .where(ContentItem.id == content_id)
            )
            resolved = row.one_or_none()
            if resolved is None:
                return 0
            _content, account, platform = resolved
            _, platform_config = await PlatformCredentialService(session, settings).resolve(
                account.workspace_id, platform.key
            )
            sync_config = await SyncRepository(session).get_sync_settings_config(
                account.workspace_id
            )
            raw_yt_config = sync_config.get("yt_dlp")
            sync_yt_config = raw_yt_config if isinstance(raw_yt_config, dict) else {}
            yt_config = {
                **platform_config,
                **sync_yt_config,
            }
            return await service.collect_content_comments(
                content_id,
                config={"yt_dlp": yt_config},
            )
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.download_url"
)
def download_url_task(self: Task, download_id: str) -> None:
    """Fetch a submitted URL with yt-dlp and store the resulting media."""
    asyncio.run(_run_download(UUID(download_id)))


async def _run_download(download_id: UUID) -> None:
    from app.adapters.platforms.yt_dlp import (
        DouyinYtDlpAdapter,
        TikTokYtDlpAdapter,
        YouTubeYtDlpAdapter,
        YtDlpAdapter,
    )
    from app.services.download import DownloadService, explain_empty_download

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    media_root = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")
    progress_sink: _DownloadProgressSink | None = None
    try:
        async with session_factory() as session:
            service = DownloadService(session)
            download = await service.get(download_id)
            if download is None:
                return
            await service.mark_running(download_id)
            progress_sink = _DownloadProgressSink(download_id, session_factory)
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
            adapter_key = detected_platform or ""
            adapter = {
                "youtube": YouTubeYtDlpAdapter,
                "tiktok": TikTokYtDlpAdapter,
                "douyin": DouyinYtDlpAdapter,
            }.get(adapter_key, YtDlpAdapter)()
            options = download.options or {}
            media_dir = os.path.join(
                media_root, str(download.workspace_id), "downloads", str(download_id)
            )
            os.makedirs(media_dir, exist_ok=True)
            await service.append_progress(download_id, ["正在解析作品地址并准备所选资源"])
            download_options = {
                "download_video": options.get("download_video", True),
                "video_quality": options.get("video_quality", "best"),
                "video_format": options.get("video_format", "best"),
                "audio_format": options.get("audio_format", "best"),
                "bitrate": options.get("bitrate", ""),
                "naming_rule": options.get("naming_rule", "id"),
                "write_subtitles": options.get("write_subtitles", True),
                "write_auto_subtitles": options.get("write_auto_subtitles", False),
                "subtitle_langs": _subtitle_language_filter(options),
                "write_thumbnail": options.get("write_thumbnail", True),
                "write_info_json": options.get("write_info_json", False),
            }
            if "subtitle_primary_lang" in options:
                download_options.update(
                    {
                        "subtitle_primary_lang": options.get("subtitle_primary_lang", ""),
                        "subtitle_secondary_lang": options.get("subtitle_secondary_lang", ""),
                        "subtitle_show_timestamps": options.get(
                            "subtitle_show_timestamps", False
                        ),
                    }
                )
            target_external_id = download.url.rstrip("/").split("/")[-1]
            raw_content_id = options.get("content_id")
            try:
                target_content_id = UUID(str(raw_content_id))
            except (TypeError, ValueError):
                target_content_id = None
            if target_content_id is not None:
                target_content = await session.scalar(
                    select(ContentItem).where(
                        ContentItem.id == target_content_id,
                        ContentItem.workspace_id == download.workspace_id,
                    )
                )
                if target_content is not None:
                    target_external_id = target_content.external_id
            entries: list[dict[str, object]] | None = None
            subtitle_browser_empty = False

            # YouTube commonly exposes captions only through
            # ``automatic_captions``. A request for "subtitles" from the
            # detail page must therefore discover the real track kind before
            # writing files; otherwise ``--write-sub`` exits successfully but
            # produces no artifact and the UI reports a misleading empty task.
            if (
                detected_platform == "youtube"
                and (
                    download_options.get("write_subtitles")
                    or download_options.get("write_auto_subtitles")
                )
                and not download_options.get("write_auto_subtitles")
            ):
                progress_sink("[youtube] 检查可用字幕轨道（人工 / 自动）…")
                try:
                    probe_entries, _ = await adapter._run_yt_dlp(
                        download.url,
                        download={},
                        structured=yt_config if isinstance(yt_config, dict) else None,
                        playlist_end=1,
                        progress_callback=None,
                        timeout_seconds=30,
                    )
                except Exception as exc:  # noqa: BLE001 - the real download remains available
                    logger.info("YouTube subtitle preflight unavailable: %s", exc)
                    probe_entries = []
                probe = probe_entries[0] if probe_entries else None
                if isinstance(probe, dict):
                    selector = str(download_options.get("subtitle_langs") or "")
                    has_manual = _has_matching_subtitle_track(probe, "subtitles", selector)
                    has_auto = _has_matching_subtitle_track(probe, "automatic_captions", selector)
                    if not has_manual and has_auto:
                        download_options["write_subtitles"] = False
                        download_options["write_auto_subtitles"] = True
                        progress_sink(
                            "[youtube] 未找到匹配的人工字幕，已切换到可用的自动字幕轨道"
                        )
            # TikTok's public page can expose a playable CDN stream even when
            # its webpage extractor rejects the same URL. Use that authorized
            # browser response first for media downloads; yt-dlp remains the
            # fallback for platforms and artifacts the browser cannot expose.
            wants_tiktok_browser_media = detected_platform == "tiktok" and any(
                download_options.get(key)
                for key in (
                    "download_video",
                    "write_subtitles",
                    "write_auto_subtitles",
                    "write_thumbnail",
                    "write_info_json",
                )
            )
            subtitle_only_request = (
                detected_platform == "tiktok"
                and (
                    download_options.get("write_subtitles")
                    or download_options.get("write_auto_subtitles")
                )
                and not download_options.get("download_video")
                and not download_options.get("write_thumbnail")
                and not download_options.get("write_info_json")
            )
            has_yt_dlp_session = _yt_dlp_session_configured(yt_config)
            if wants_tiktok_browser_media:
                from app.adapters.platforms.base import AdapterCallContext
                from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter

                browser_adapter = TikTokBrowserAdapter()
                try:
                    progress_sink("[tiktok_browser] 切换公开浏览器媒体通道，避免重复网页解析失败")
                    browser_entry = await asyncio.wait_for(
                        browser_adapter.download_public_media(
                            AdapterCallContext(
                                config=yt_config if isinstance(yt_config, dict) else {},
                                observed_at=datetime.now(UTC),
                                request_id=str(download_id),
                                progress_sink=progress_sink,
                            ),
                            download.url,
                            target_external_id,
                            media_dir,
                            download_options,
                        ),
                        timeout=75,
                    )
                    if browser_entry is not None and not (
                        subtitle_only_request
                        and browser_entry.get("_sio_empty_reason")
                        and has_yt_dlp_session
                    ):
                        entries = [browser_entry]
                    elif subtitle_only_request and browser_entry is not None:
                        subtitle_browser_empty = bool(browser_entry.get("_sio_empty_reason"))
                        progress_sink(
                            "[tiktok_browser] 公开字幕未匹配所选语种；"
                            "授权 Cookie 通道仅尝试一次，避免重复网页解析"
                        )
                    elif subtitle_only_request and not has_yt_dlp_session:
                        entries = [
                            {
                                "id": target_external_id,
                                "extractor": "tiktok_browser",
                                "_sio_empty_reason": (
                                    "TikTok 公开页未返回可识别的字幕数据。"
                                    "已停止 yt-dlp 网页解析回退，避免重复触发相同错误。"
                                ),
                            }
                        ]
                    elif subtitle_only_request:
                        progress_sink(
                            "[tiktok_browser] 公开字幕未匹配所选语种，"
                            "检测到已配置 Cookie，"
                            "切换 yt-dlp Cookie 字幕通道"
                        )
                except Exception as exc:  # noqa: BLE001 - yt-dlp is the bounded fallback
                    logger.info("TikTok browser media path unavailable: %s", exc)
                    progress_sink(
                        (
                            "[tiktok_browser] 公开字幕通道未产出文件，停止 yt-dlp 网页解析回退："
                            if subtitle_only_request
                            else "[tiktok_browser] 公开媒体通道未产出文件，切换 yt-dlp 后备通道："
                        )
                        + str(exc)
                    )
                    if subtitle_only_request and not has_yt_dlp_session:
                        entries = [
                            {
                                "id": target_external_id,
                                "extractor": "tiktok_browser",
                                "_sio_empty_reason": (
                                    "TikTok 公开字幕通道暂时不可用："
                                    f"{exc}。已停止 yt-dlp 网页解析回退。"
                                ),
                            }
                        ]
                    elif subtitle_only_request:
                        progress_sink(
                            "[tiktok_browser] 公开字幕通道异常，"
                            "检测到已配置 Cookie，"
                            "切换 yt-dlp Cookie 字幕通道"
                        )
                finally:
                    await browser_adapter.aclose()

            try:
                if entries is None:
                    ytdlp_download_config = (
                        {**yt_config, "extraction_attempts": 1, "retries": 0}
                        if subtitle_browser_empty and isinstance(yt_config, dict)
                        else yt_config
                    )
                    entries, _ = await adapter._run_yt_dlp(
                        download.url,
                        download=download_options,
                        structured=(
                            ytdlp_download_config
                            if isinstance(ytdlp_download_config, dict)
                            else None
                        ),
                        media_dir=media_dir,
                        playlist_end=1,
                        progress_callback=progress_sink,
                    )
            except Exception:
                # A metadata-only request from the content detail page must
                # remain useful when the platform temporarily rejects yt-dlp.
                # The fallback is an explicitly labelled snapshot of fields
                # already acquired into this workspace; it is never presented
                # as a fresh raw platform response.
                fallback_entries = await _build_archived_metadata_entry(
                    session,
                    download,
                    options,
                    media_root,
                    media_dir,
                )
                if not fallback_entries:
                    raise
                progress_sink("yt-dlp 暂时不可用，改用已入库公开字段生成归档元信息快照")
                entries = fallback_entries
            finally:
                await progress_sink.close()
                progress_sink = None
            media = None
            platform = None
            for entry in entries:
                vid = entry.get("id")
                if not vid:
                    continue
                collected = YtDlpAdapter._collect_media(media_root, media_dir, str(vid))
                if collected:
                    media = collected
                    raw_platform = entry.get("extractor") or entry.get("ie_key")
                    platform = str(raw_platform) if raw_platform else None
                    break
            if media:
                await reconcile_manifest(
                    session,
                    workspace_id=download.workspace_id,
                    download_id=download.id,
                    media=media,
                    source_kind="live",
                    source_provider=str(platform or detected_platform or "yt_dlp"),
                    source_url=download.url,
                )
            if media and options.get("content_id"):
                await _attach_download_to_content(
                    session,
                    download,
                    str(options["content_id"]),
                    media,
                    media_root,
                    subtitle_show_timestamps=bool(
                        options.get("subtitle_show_timestamps")
                    ),
                )
            elif media and options.get("save_to_works") and entries:
                await _save_download_as_work(session, download, entries[0], media)
            empty_reason = None if media else explain_empty_download(dict(options), entries)
            await service.mark_done(download_id, media, platform, empty_reason)
    except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
        logger.warning("download %s failed: %s", download_id, exc)
        if progress_sink is not None:
            try:
                await progress_sink.close()
            except Exception:  # noqa: BLE001 - terminal failure must still persist
                logger.warning("download %s progress flush failed", download_id, exc_info=True)
        async with session_factory() as session:
            await DownloadService(session).mark_failed(download_id, str(exc))
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="app.tasks.monitoring.preview_download"
)
def preview_download_task(self: Task, url: str, workspace_id: str) -> dict[str, Any]:
    """Parse a video URL with yt-dlp for the download preview card.

    Mirrors ``download_url_task`` but only extracts metadata (no media save),
    and returns a JSON-serializable result dict the API polls for.
    """

    return asyncio.run(_run_preview(url, UUID(workspace_id)))


async def _run_preview(url: str, workspace_id: UUID) -> dict[str, Any]:
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
        existing.media = merge_media_manifest(existing.media, media)
        return
    now = datetime.now(UTC)
    published_at = None
    raw_timestamp = entry.get("timestamp")
    if raw_timestamp is not None:
        try:
            published_at = datetime.fromtimestamp(float(str(raw_timestamp)), tz=UTC)
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


async def _attach_download_to_content(
    session: AsyncSession,
    download: Download,
    content_id: str,
    media: dict[str, object],
    media_root: str,
    *,
    subtitle_show_timestamps: bool | None = None,
) -> None:
    """Merge on-demand artifacts into the exact work that opened the modal.

    Download jobs use their own directory. When the work already has a media
    manifest, copy the new files into that manifest's directory before merging;
    otherwise the content media endpoint would see one base directory with
    filenames that actually live in another directory.
    """

    try:
        target_id = UUID(content_id)
    except (TypeError, ValueError):
        logger.warning("download %s has invalid content_id %s", download.id, content_id)
        return
    content = await session.scalar(
        select(ContentItem).where(
            ContentItem.id == target_id,
            ContentItem.workspace_id == download.workspace_id,
        )
    )
    if content is None:
        logger.warning("download %s target content %s not found", download.id, content_id)
        return

    existing = dict(content.media or {})
    source_base = str(media.get("base") or "")
    target_base = str(existing.get("base") or "")
    if source_base and target_base and source_base != target_base:
        source_dir = os.path.join(media_root, source_base)
        target_dir = os.path.join(media_root, target_base)
        os.makedirs(target_dir, exist_ok=True)
        filenames: list[str] = []
        for key in ("video", "audio", "thumbnail", "info_json"):
            value = media.get(key)
            if isinstance(value, str) and value:
                filenames.append(value)
        raw_subtitles = media.get("subtitles")
        if isinstance(raw_subtitles, list):
            for item in raw_subtitles:
                if isinstance(item, dict) and isinstance(item.get("file"), str):
                    filenames.append(item["file"])
        for filename in filenames:
            safe_name = os.path.basename(filename)
            source = os.path.join(source_dir, safe_name)
            target = os.path.join(target_dir, safe_name)
            if await asyncio.to_thread(os.path.isfile, source):
                await asyncio.to_thread(shutil.copy2, source, target)
        merged = merge_media_manifest(existing, {**media, "base": target_base}) or {
            "base": target_base
        }
    else:
        merged = merge_media_manifest(existing, media) or existing
    if subtitle_show_timestamps is not None and media.get("subtitles"):
        merged["subtitle_show_timestamps"] = subtitle_show_timestamps
    content.media = merged
    content.last_seen_at = datetime.now(UTC)
    content.fetched_at = content.last_seen_at
    await session.commit()


async def _build_archived_metadata_entry(
    session: AsyncSession,
    download: Download,
    options: dict[str, object],
    media_root: str,
    media_dir: str,
) -> list[dict[str, object]]:
    """Create a clearly labelled info.json from the selected work snapshot."""

    if not options.get("write_info_json"):
        return []
    if any(
        options.get(key)
        for key in ("download_video", "write_subtitles", "write_auto_subtitles", "write_thumbnail")
    ):
        return []
    content_id = options.get("content_id")
    try:
        target_id = UUID(str(content_id))
    except (TypeError, ValueError):
        return []
    content = await session.scalar(
        select(ContentItem).where(
            ContentItem.id == target_id,
            ContentItem.workspace_id == download.workspace_id,
        )
    )
    if content is None:
        return []
    entry: dict[str, object] = {
        "id": content.external_id,
        "title": content.title,
        "description": content.description,
        "webpage_url": content.canonical_url,
        "thumbnail": content.cover_url,
        "upload_date": content.published_at.strftime("%Y%m%d")
        if content.published_at
        else None,
        "extractor": "sio_archived_content",
        "sio_metadata_source": "archived_content_snapshot",
        "sio_metadata_notice": (
            "yt-dlp 本次未能解析源站；此文件由已入库的公开作品字段生成，"
            "不代表本次重新抓取的原始平台响应。"
        ),
        "sio_archived_at": datetime.now(UTC).isoformat(),
        "sio_content_metadata": dict(content.metadata_json or {}),
    }
    item_dir = os.path.join(media_dir, content.external_id)
    await asyncio.to_thread(os.makedirs, item_dir, exist_ok=True)
    info_name = f"{content.external_id}.info.json"
    info_path = os.path.join(item_dir, info_name)
    await asyncio.to_thread(
        _write_json_file,
        info_path,
        entry,
    )
    # Keep the parameter in the signature so the helper's output directory is
    # visibly tied to the same MEDIA_ROOT used by the normal collector.
    del media_root
    return [entry]


def _write_json_file(path: str, payload: dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


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


async def _recover_stale_downloads() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            return await DownloadService(session).recover_stale_downloads(
                datetime.now(UTC) - timedelta(seconds=settings.download_stale_after_seconds)
            )
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.monitoring.recover_stale_downloads"
)
def recover_stale_downloads() -> int:
    """Release dead download jobs quickly so the UI never spins forever."""

    return asyncio.run(_recover_stale_downloads())


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
