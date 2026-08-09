"""Service layer for on-demand downloads."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.download import Download
from app.schemas.download import (
    DownloadCreate,
    DownloadPage,
    DownloadPreviewRead,
    DownloadRead,
)

logger = logging.getLogger(__name__)

# Shared user-facing copy for "we could not resolve this URL at all". Kept as a
# constant so the API and the Celery task never drift apart (and so the line
# stays inside the 100 char lint budget).
UNRESOLVABLE_URL_DETAIL = (
    "无法解析该地址：该平台或链接可能受登录墙、限流或地域限制，请确认链接正确且公开可访问。"
)


def _youtube_video_id(value: str) -> str | None:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            candidate = (
                parts[1] if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"} else ""
            )
    else:
        return None
    return candidate if candidate and len(candidate) <= 32 else None


async def _youtube_oembed_preview(url: str) -> DownloadPreviewRead | None:
    """Return public title/cover metadata when YouTube temporarily rate-limits yt-dlp.

    oEmbed is a public metadata endpoint, not a bypass.  It cannot provide
    subtitles or download URLs, so the response explicitly tells the UI that
    only the preview was completed.
    """

    video_id = _youtube_video_id(url)
    if not video_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                headers={"User-Agent": "Content-Intelligence-OS/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("title"):
        return None
    return DownloadPreviewRead(
        url=url,
        platform="youtube",
        external_id=video_id,
        title=str(payload["title"]),
        uploader=str(payload.get("author_name") or "") or None,
        thumbnail=str(payload.get("thumbnail_url") or "") or None,
        duration_seconds=None,
        description=None,
        subtitle_languages=[],
        notice=(
            "YouTube 当前对解析请求返回 429，已使用公开页面元数据完成预览；"
            "字幕与实际媒体将在异步任务中再次探测。若任务仍失败，请等待限流解除后重试。"
        ),
    )


async def build_download_preview(
    url: str, workspace_id: UUID, settings: Settings
) -> dict[str, Any]:
    """Run yt-dlp metadata extraction for the preview, off the request path.

    Called from a Celery task (``app.tasks.monitoring.preview_download_task``).
    Returns a JSON-serializable result dict understood by the polling endpoint:

        {"status": "ok", "preview": <DownloadPreviewRead dict>}
        {"status": "error", "error_code": int, "error_detail": str}
    """

    from app.adapters.platforms.yt_dlp import YtDlpAdapter
    from app.db.session import create_engine_and_session
    from app.providers.news.utils import ensure_public_media_endpoint
    from app.repositories.sync import SyncRepository
    from app.services.platform_credentials import PlatformCredentialService
    from app.services.platform_detect import detect_platform_key_from_url

    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            sync_config = await SyncRepository(session).get_sync_settings_config(workspace_id)
        yt_config = sync_config.get("yt_dlp")
        preview_config = dict(yt_config) if isinstance(yt_config, dict) else {}
        detected_platform = detect_platform_key_from_url(url)
        if detected_platform:
            async with session_factory() as session:
                _, platform_config = await PlatformCredentialService(session, settings).resolve(
                    workspace_id, detected_platform
                )
            preview_config = {**platform_config, **preview_config}
        # Preview should remain responsive, while inheriting authentication and
        # extraction settings saved for this workspace.
        preview_config.update({"retries": 3, "sleep_requests": 1})
        try:
            url = await ensure_public_media_endpoint(url)
            entries, _ = await YtDlpAdapter()._run_yt_dlp(
                url,
                download={},
                playlist_end=1,
                structured=preview_config,
            )
        except Exception as exc:  # noqa: BLE001 - map to a safe, actionable error
            logger.warning("preview_download failed for %s: %s", url, exc)
            if _youtube_video_id(url) is not None and (
                "429" in str(exc) or "too many requests" in str(exc).lower()
            ):
                fallback = await _youtube_oembed_preview(url)
                if fallback is not None:
                    return {"status": "ok", "preview": fallback.model_dump(mode="json")}
                return {
                    "status": "error",
                    "error_code": 429,
                    "error_detail": (
                        "YouTube 暂时限流（429），Node.js 只能补齐 JavaScript 解析能力，"
                        "不能解除平台限流；请等待后重试，或使用已获授权的浏览器会话/官方 API。"
                    ),
                }
            # Do not echo the raw exception (it may contain local paths); the
            # real error is logged server-side for operators.
            return {
                "status": "error",
                "error_code": 422,
                "error_detail": UNRESOLVABLE_URL_DETAIL,
            }
        if not entries:
            return {
                "status": "error",
                "error_code": 422,
                "error_detail": "地址未返回可识别的视频信息",
            }
        item = entries[0]
        subtitle_languages = sorted(
            {
                str(language)
                for key in ("subtitles", "automatic_captions")
                for language in (item.get(key) or {})
                if language
            }
        )
        preview = DownloadPreviewRead(
            url=url,
            platform=str(item.get("extractor") or item.get("ie_key") or "") or None,
            external_id=str(item.get("id")) if item.get("id") else None,
            title=str(item.get("title")) if item.get("title") else None,
            uploader=str(item.get("uploader") or item.get("channel") or "") or None,
            thumbnail=str(item.get("thumbnail")) if item.get("thumbnail") else None,
            duration_seconds=(
                float(item["duration"]) if item.get("duration") is not None else None
            ),
            description=str(item.get("description")) if item.get("description") else None,
            subtitle_languages=subtitle_languages,
        )
        return {"status": "ok", "preview": preview.model_dump(mode="json")}
    finally:
        await engine.dispose()


class DownloadService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, workspace_id: UUID, payload: DownloadCreate) -> DownloadRead:
        now = datetime.now(UTC)
        download = Download(
            workspace_id=workspace_id,
            url=payload.url.strip(),
            status="pending",
            options={
                "download_video": payload.download_video,
                "video_quality": payload.video_quality,
                "video_format": payload.video_format,
                "audio_format": payload.audio_format,
                "bitrate": payload.bitrate,
                "naming_rule": payload.naming_rule,
                "write_subtitles": payload.write_subtitles,
                "write_auto_subtitles": payload.write_auto_subtitles,
                "subtitle_langs": payload.subtitle_langs,
                "write_thumbnail": payload.write_thumbnail,
                "write_info_json": payload.write_info_json,
                "save_to_works": payload.save_to_works,
            },
            created_at=now,
            updated_at=now,
        )
        self._session.add(download)
        await self._session.commit()
        await self._session.refresh(download)
        return DownloadRead.model_validate(download)

    async def list(self, workspace_id: UUID, *, page: int = 1, page_size: int = 20) -> DownloadPage:
        conditions = [Download.workspace_id == workspace_id]
        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(Download).where(*conditions)
                )
            )
            or 0
        )
        rows = (
            await self._session.scalars(
                select(Download)
                .where(*conditions)
                .order_by(Download.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return DownloadPage(
            items=[DownloadRead.model_validate(r) for r in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get(self, download_id: UUID) -> Download | None:
        return await self._session.get(Download, download_id)

    async def mark_running(self, download_id: UUID) -> None:
        download = await self._session.get(Download, download_id)
        if download is None:
            return
        download.status = "running"
        download.updated_at = datetime.now(UTC)
        await self._session.commit()

    async def mark_done(
        self,
        download_id: UUID,
        media: dict[str, Any] | None,
        platform: str | None,
        empty_reason: str | None = None,
    ) -> None:
        """Persist a finished download.

        ``empty_reason`` explains *why* nothing was produced when ``media`` is
        empty. Without it the UI can only say "no files", which is misleading:
        "the platform has no subtitle track for this video" and "your quality
        settings excluded every format" are very different problems.
        """

        download = await self._session.get(Download, download_id)
        if download is None:
            return
        download.status = "done" if media else "empty"
        download.media = media
        download.platform = platform
        download.error = None if media else (empty_reason or None)
        download.updated_at = datetime.now(UTC)
        await self._session.commit()


def explain_empty_download(
    options: dict[str, Any],
    entries: list[dict[str, Any]],
) -> str:
    """Return an actionable reason for a download that produced no files."""

    if not entries:
        return "未从该地址解析到任何视频条目，请确认链接有效且内容公开可访问。"

    entry = entries[0] or {}
    wants_video = bool(options.get("download_video"))
    wants_subs = bool(options.get("write_subtitles")) or bool(options.get("write_auto_subtitles"))
    wants_thumb = bool(options.get("write_thumbnail"))

    if wants_subs and not wants_video:
        available = sorted(
            {
                str(lang)
                for key in ("subtitles", "automatic_captions")
                for lang in (entry.get(key) or {})
                if lang
            }
        )
        if not available:
            platform = str(entry.get("extractor") or entry.get("ie_key") or "该平台")
            return (
                f"{platform} 未对这条视频提供任何字幕轨（人工字幕与自动字幕均为空），"
                "因此没有字幕文件可下载。这不是设置问题。"
            )
        requested = str(options.get("subtitle_langs") or "").strip()
        return (
            f"该视频有字幕语言 {', '.join(available[:8])}，但与请求的语言过滤 "
            f"“{requested or '(默认)'}” 不匹配，请调整字幕语言后重试。"
        )

    if wants_video:
        return (
            "视频文件未能写入：可能是所选清晰度/格式在该平台不存在，"
            "或媒体分片下载被中断，请更换清晰度后重试。"
        )
    if wants_thumb:
        return "该视频未提供可下载的封面图。"
    return "本次任务未开启任何会产生文件的选项（视频 / 字幕 / 封面 / info.json）。"

    async def mark_failed(self, download_id: UUID, error: str) -> None:
        download = await self._session.get(Download, download_id)
        if download is None:
            return
        download.status = "failed"
        download.error = error[:2000]
        download.updated_at = datetime.now(UTC)
        await self._session.commit()
