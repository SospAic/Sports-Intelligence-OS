# ruff: noqa: E501, I001, S110
"""TikTok browser-simulation adapter.

Scrapes public TikTok profile pages using a headless browser. No API key
required — works by rendering the page and extracting data from the DOM
or intercepting XHR responses.

Supports:
- No credentials: scrapes public profile info and video lists.
- Optional login for authenticated content.

Registered as 'tiktok_browser', coexists with the API-based 'tiktok' adapter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterContractError,
    AdapterDescriptor,
    AdapterPage,
    PlatformAccountData,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)
from app.adapters.platforms.browser_base import (
    BrowserPlatformAdapter,
    LoginRequiredError,
    reraise_if_terminal,
)
from app.adapters.platforms.profile_helpers import is_anti_bot_shell_profile

logger = logging.getLogger(__name__)

TIKTOK_PROFILE_URL = "https://www.tiktok.com/@{username}"
TIKTOK_VIDEO_URL = "https://www.tiktok.com/@{username}/video/{video_id}"
# TikTok's public profile item-list endpoint currently returns a 15-item
# window even when a larger page is requested. Keep the cursor aligned with
# that platform window instead of asking the sync engine to skip past items
# that the browser has not materialised yet.
TIKTOK_PROFILE_PAGE_SIZE = 15


def _profile_pagination_window(offset: int, page_size: int) -> tuple[int, int]:
    """Return the effective TikTok page size and required scroll rounds."""

    effective_page_size = min(max(1, int(page_size)), TIKTOK_PROFILE_PAGE_SIZE)
    target_end = offset + effective_page_size
    materialization_pages = max(
        1,
        (target_end + TIKTOK_PROFILE_PAGE_SIZE - 1) // TIKTOK_PROFILE_PAGE_SIZE,
    )
    return effective_page_size, min(40, 5 + materialization_pages * 5)


def _write_binary_file(path: str, payload: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(payload)


def _write_json_file(path: str, payload: Mapping[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)


def _safe_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


class TikTokBrowserAdapter(BrowserPlatformAdapter):
    """Scrapes TikTok public pages via headless Chromium."""

    reuse_connected_context = True

    descriptor = AdapterDescriptor(
        key="tiktok_browser",
        name="TikTok（合规公开页）",
        implementation_status="implemented",
        capabilities={
            AdapterCapability.PUBLIC_PROFILE: True,
            AdapterCapability.ACCOUNT_ANALYTICS: True,
            AdapterCapability.CONTENT_LIST: True,
            AdapterCapability.CONTENT_ANALYTICS: False,
            AdapterCapability.TRAFFIC_SOURCES: False,
            AdapterCapability.RETENTION: False,
            AdapterCapability.REVENUE: False,
            # The public web comment endpoint returns ranked top-level comments
            # for public videos.  Keep yt-dlp as a fallback for an authorized
            # session, but prefer this browser-context path because TikTok's
            # webpage extractor often fails while the public JSON endpoint is
            # still readable.
            AdapterCapability.COMMENTS: True,
            AdapterCapability.SEARCH_TERMS: False,
        },
        config_fields=(),
        source_kinds=frozenset({"live"}),
    )

    min_action_delay = 1.5

    @staticmethod
    def _safe_media_dir(name: str) -> str:
        """Keep profile media directories stable and filesystem-safe."""

        cleaned = re.sub(r"[^A-Za-z0-9_@.-]", "_", name or "unknown")
        return cleaned[:120] or "unknown"

    async def _archive_profile_thumbnails(
        self,
        context: Any,
        ctx: AdapterCallContext,
        username: str,
        items: Sequence[PlatformContentData],
    ) -> tuple[PlatformContentData, ...]:
        """Archive public profile thumbnails without slowing item ingestion.

        TikTok profile cards expose signed CDN URLs. They are valid for the
        browser session but can expire before a user opens the works page, so
        retaining only ``cover_url`` is not sufficient. This bounded, optional
        side path copies the public bytes into the workspace media root and
        returns a local media manifest. A failed cover never drops the work or
        turns a successful page into a failed sync.
        """

        config = ctx.config or {}
        download = config.get("download") if isinstance(config, Mapping) else None
        media_root = config.get("media_root") if isinstance(config, Mapping) else None
        if not (
            isinstance(download, Mapping)
            and download.get("write_thumbnail")
            and isinstance(media_root, str)
            and media_root
        ):
            return tuple(items)

        global_media_root = os.path.dirname(media_root)
        account_dir = os.path.join(media_root, self._safe_media_dir(username))
        semaphore = asyncio.Semaphore(4)
        archived = 0
        failed = 0

        async def archive(item: PlatformContentData) -> PlatformContentData:
            nonlocal archived, failed
            if isinstance(item.media, Mapping) and item.media.get("thumbnail"):
                return item
            cover_url = self._public_media_url(item.cover_url)
            if not cover_url:
                return item
            parsed = urlparse(cover_url)
            suffix = os.path.splitext(parsed.path)[1].lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = ".jpg"
            item_dir = os.path.join(account_dir, self._safe_media_dir(item.external_id))
            filename = f"{self._safe_media_dir(item.external_id)}{suffix}"
            target = os.path.join(item_dir, filename)
            relative_base = str(Path(item_dir).relative_to(Path(global_media_root)))
            try:
                async with semaphore:
                    await asyncio.to_thread(os.makedirs, item_dir, exist_ok=True)
                    if not await asyncio.to_thread(os.path.isfile, target):
                        response = await context.request.get(
                            cover_url,
                            headers={"Referer": item.canonical_url, "Accept": "image/*"},
                            timeout=15_000,
                        )
                        if not response.ok:
                            failed += 1
                            return item
                        body = await response.body()
                        if not body:
                            failed += 1
                            return item
                        await asyncio.to_thread(_write_binary_file, target, body)
                    archived += 1
                    return replace(
                        item,
                        media={
                            **dict(item.media or {}),
                            "base": relative_base,
                            "thumbnail": filename,
                        },
                    )
            except Exception as exc:  # noqa: BLE001 - one cover must not drop a page
                failed += 1
                logger.debug("TikTok thumbnail archive failed for %s: %s", item.external_id, exc)
                return item

        result = await asyncio.gather(*(archive(item) for item in items))
        sink = getattr(ctx, "progress_sink", None)
        if callable(sink) and (archived or failed):
            sink(f"[cover] 本页封面已归档 {archived}/{len(items)} 条" + (f"，失败 {failed} 条" if failed else ""))
        return tuple(result)

    @staticmethod
    def _find_post_payload(value: Any, external_id: str, depth: int = 0) -> Mapping[str, Any] | None:
        """Find one public TikTok item in an intercepted JSON response."""

        if depth > 10:
            return None
        if isinstance(value, Mapping):
            candidate_id = value.get("id") or value.get("aweme_id") or value.get("video_id")
            if str(candidate_id or "") == str(external_id) and isinstance(value.get("video"), Mapping):
                return value
            for child in value.values():
                found = TikTokBrowserAdapter._find_post_payload(child, external_id, depth + 1)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = TikTokBrowserAdapter._find_post_payload(child, external_id, depth + 1)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _public_media_url(value: Any) -> str | None:
        """Accept only URLs returned by TikTok's own public media payload."""

        candidates: list[str] = []
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, Mapping):
            urls = value.get("urlList") or value.get("url_list")
            if isinstance(urls, list):
                candidates.extend(item for item in urls if isinstance(item, str))
            for key in ("url", "Url", "uri"):
                item = value.get(key)
                if isinstance(item, str):
                    candidates.append(item)
        allowed_suffixes = (
            ".tiktokcdn.com",
            ".ibytedtos.com",
            ".tiktokv.com",
            ".muscdn.com",
        )
        for candidate in candidates:
            parsed = urlparse(candidate)
            hostname = (parsed.hostname or "").lower()
            if parsed.scheme in {"http", "https"} and (
                hostname.endswith(allowed_suffixes) or hostname.endswith(".tiktok.com")
            ):
                return candidate
        return None

    @classmethod
    def _select_public_video_url(
        cls, video: Mapping[str, Any]
    ) -> tuple[str | None, str]:
        """Prefer TikTok's public playback stream without modifying the media.

        ``playAddr`` is the closest public signal to a playback stream, but
        TikTok may still include a watermark in that stream.  The adapter must
        therefore never claim that it removed a watermark: it only selects a
        platform-provided URL and falls back to ``downloadAddr`` when no public
        playback URL is available.
        """

        playback_url = cls._public_media_url(
            video.get("playAddr")
            or video.get("play_addr")
            or video.get("playAddrStruct")
        )
        if playback_url:
            return playback_url, "public_playback"
        download_url = cls._public_media_url(
            video.get("downloadAddr") or video.get("download_addr")
        )
        if download_url:
            return download_url, "public_download"
        return None, "unavailable"

    @staticmethod
    def _subtitle_candidates(item: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw_video = item.get("video")
        video: Mapping[str, Any] = raw_video if isinstance(raw_video, Mapping) else {}
        raw = video.get("subtitleInfos") or video.get("subtitle_infos") or []
        if not isinstance(raw, list):
            return []
        result: list[dict[str, Any]] = []
        for info in raw:
            if not isinstance(info, Mapping):
                continue
            url = TikTokBrowserAdapter._public_media_url(
                info.get("Url") or info.get("url") or info.get("urlList") or info.get("url_list")
            )
            if not url:
                continue
            language = str(
                info.get("LanguageCode")
                or info.get("languageCode")
                or info.get("language")
                or "und"
            ).strip()
            source = str(info.get("Source") or info.get("source") or "").casefold()
            is_auto = bool(
                info.get("IsAutoGenerated")
                or info.get("isAutoGenerated")
                or info.get("is_auto_generated")
                or "auto" in source
                or source in {"asr", "mt"}
            )
            result.append({"url": url, "language": language, "auto": is_auto})
        return result

    @staticmethod
    def _normalize_public_comments(
        payload: Mapping[str, Any], *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Normalize TikTok's public ``/api/comment/list`` response.

        This endpoint is a read-only public-page data source; it is not an
        attempt to bypass a login wall or challenge.  TikTok calls the useful
        fields ``cid``, ``digg_count`` and ``create_time`` and nests author
        identity under ``user``.  Keep the raw ranking order as a tie-breaker,
        while exposing the real like/reply/time fields to the unified model.
        """

        raw_comments = payload.get("comments")
        if not isinstance(raw_comments, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in raw_comments:
            if not isinstance(item, Mapping):
                continue
            text = str(item.get("text") or "").strip()
            comment_id = str(item.get("cid") or item.get("comment_id") or "").strip()
            if not text or not comment_id:
                continue
            raw_user = item.get("user")
            user: Mapping[str, Any] = raw_user if isinstance(raw_user, Mapping) else {}
            raw_avatar = user.get("avatar_thumb")
            avatar: Mapping[str, Any] = (
                raw_avatar if isinstance(raw_avatar, Mapping) else {}
            )
            raw_avatar_urls = avatar.get("url_list")
            avatar_urls: list[Any] = (
                raw_avatar_urls if isinstance(raw_avatar_urls, list) else []
            )
            avatar_url = next(
                (str(candidate) for candidate in avatar_urls if isinstance(candidate, str) and candidate),
                None,
            )
            unique_id = str(user.get("unique_id") or user.get("uniqueId") or "").strip()
            parent_id: str | None = str(item.get("reply_id") or "").strip()
            if parent_id in {"", "0"}:
                parent_id = None
            timestamp = item.get("create_time")
            published_at = None
            if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
                try:
                    published_at = datetime.fromtimestamp(timestamp, tz=UTC)
                except (OverflowError, OSError, ValueError):
                    published_at = None
            normalized.append(
                {
                    "platform_comment_id": comment_id,
                    "author_name": str(user.get("nickname") or user.get("unique_id") or "未知用户"),
                    "author_url": (
                        f"https://www.tiktok.com/@{unique_id}" if unique_id else None
                    ),
                    "author_avatar_url": avatar_url,
                    "text": text,
                    "like_count": _safe_nonnegative_int(item.get("digg_count")),
                    "reply_count": _safe_nonnegative_int(item.get("reply_comment_total")),
                    "parent_comment_id": parent_id,
                    "is_reply": parent_id is not None,
                    "published_at": published_at,
                }
            )
        return normalized[: max(1, min(int(limit or 20), 20))]

    async def extract_public_comments(
        self,
        ctx: AdapterCallContext,
        url: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Read ranked public comments through the browser request context.

        TikTok can return ``ERR_HTTP_RESPONSE_CODE_FAILURE`` for the video
        document while its public comment JSON endpoint remains available.  A
        browser-context request preserves the same public session and avoids
        making the user wait through three identical webpage-extractor retries.
        """

        match = re.search(r"/video/(\d+)", url)
        if not match:
            return []
        external_id = match.group(1)
        context = None
        try:
            context = await self._new_context(ctx)
            endpoint = (
                "https://www.tiktok.com/api/comment/list/"
                f"?aid=1988&aweme_id={external_id}&count={max(1, min(int(limit or 20), 20))}"
                "&cursor=0&device_platform=webapp"
            )
            response = await context.request.get(
                endpoint,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": url,
                },
                timeout=20_000,
            )
            if not response.ok:
                self._progress(ctx, f"[tiktok_browser] 评论接口返回 HTTP {response.status}")
                return []
            payload = await response.json()
            if not isinstance(payload, Mapping):
                return []
            return self._normalize_public_comments(payload, limit=limit)
        finally:
            if context is not None:
                await self._dispose_context(context)

    async def download_public_media(
        self,
        ctx: AdapterCallContext,
        url: str,
        external_id: str,
        media_dir: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Download public media URLs exposed to an authorized browser page.

        TikTok's webpage extractor can fail while the same public page still
        exposes a playable CDN stream in the browser. This path uses only the
        page's own response payload and browser request context; it does not
        bypass a challenge or manufacture a media URL.
        """

        captured: Mapping[str, Any] | None = None
        observed_media_urls: list[str] = []
        # Subtitle-only downloads do not need the video document at all.  The
        # document is the endpoint that most often returns TikTok's
        # anti-bot/HTTP failure, so going there first only adds three identical
        # navigation attempts before we reach the profile JSON that can expose
        # the same subtitle metadata.  Start from the public profile for this
        # narrow request; video/cover/info downloads keep the direct-page path
        # because they need the richer post payload.
        wants_subtitles = bool(options.get("write_subtitles")) or bool(
            options.get("write_auto_subtitles")
        )
        subtitle_only_request = (
            wants_subtitles
            and not bool(options.get("download_video"))
            and not bool(options.get("write_thumbnail"))
            and not bool(options.get("write_info_json"))
        )
        username_match = re.search(r"tiktok\.com/@([^/?#]+)/video/", url, re.I)
        profile_url = (
            TIKTOK_PROFILE_URL.format(username=username_match.group(1))
            if username_match
            else None
        )
        initial_url = profile_url if subtitle_only_request and profile_url else url
        if initial_url != url:
            self._progress(
                ctx,
                "[tiktok_browser] 字幕任务直接读取公开主页，跳过作品页重复重试",
            )

        async def capture(response: Any) -> None:
            nonlocal captured
            response_url = response.url
            if "/api/" not in response_url:
                parsed = urlparse(response_url)
                hostname = (parsed.hostname or "").lower()
                content_type = str(response.headers.get("content-type") or "").casefold()
                if hostname.endswith(
                    (".tiktok.com", ".tiktokcdn.com", ".ibytedtos.com", ".tiktokv.com", ".muscdn.com")
                ) and ("video/" in content_type or "audio/" in content_type or ".mp4" in response_url):
                    if response_url not in observed_media_urls:
                        observed_media_urls.append(response_url)
                return
            try:
                payload = await response.json()
            except Exception:  # noqa: BLE001 - unrelated API responses are common
                return
            found = self._find_post_payload(payload, external_id)
            if found is not None:
                captured = found

        context = None
        page: Page | None = None
        try:
            try:
                context, page = await self._navigate(
                    ctx,
                    initial_url,
                    wait_until="domcontentloaded",
                    timeout=self.page_load_timeout_ms,
                    response_handler=capture,
                )
            except Exception as detail_exc:
                # TikTok may reject a direct /video/ navigation from the
                # container while allowing the same public profile page used
                # by account sync. Reuse that successful catalogue route and
                # locate the requested item in its intercepted item-list JSON.
                if not profile_url or initial_url == profile_url:
                    raise
                self._progress(
                    ctx,
                    f"[tiktok_browser] 作品页打开失败，改用公开主页响应定位作品：{detail_exc}",
                )
                context, page = await self._navigate(
                    ctx,
                    profile_url,
                    wait_until="domcontentloaded",
                    timeout=self.page_load_timeout_ms,
                    response_handler=capture,
                )
            await self._polite_delay(1.0)
            await self._check_login_required(page, "TikTok")
            if captured is None:
                await self._scroll_page(page, times=8, ctx=ctx)
            if captured is None:
                if profile_url and initial_url != profile_url:
                    await self._dispose_context(context, page)
                    context = None
                    page = None
                    self._progress(ctx, "[tiktok_browser] 作品页未返回媒体数据，改从公开主页重新定位作品")
                    context, page = await self._navigate(
                        ctx,
                        profile_url,
                        wait_until="domcontentloaded",
                        timeout=self.page_load_timeout_ms,
                        response_handler=capture,
                    )
                    await self._polite_delay(1.0)
                    await self._check_login_required(page, "TikTok")
                    await self._scroll_page(page, times=8, ctx=ctx)
            if captured is None and observed_media_urls:
                captured = {
                    "id": external_id,
                    "video": {"playAddr": observed_media_urls[0]},
                }
            if captured is None:
                self._progress(ctx, "[tiktok_browser] 未捕获到作品媒体响应，保留 yt-dlp 后备通道")
                return None

            captured_payload: Mapping[str, Any] = captured
            raw_video = captured_payload.get("video")
            video: Mapping[str, Any] = raw_video if isinstance(raw_video, Mapping) else {}
            video_url, video_source = self._select_public_video_url(video)
            if video_url is None and observed_media_urls:
                video_url = self._public_media_url(observed_media_urls[0])
                video_source = "observed_public_playback"
                self._progress(ctx, "[tiktok_browser] 从公开 CDN 视频响应恢复播放地址")
            wants_video = bool(options.get("download_video")) and str(
                options.get("video_quality") or "best"
            ).casefold() != "audio"
            subtitles = self._subtitle_candidates(captured_payload)
            wants_manual_subtitles = bool(options.get("write_subtitles"))
            wants_auto_subtitles = bool(options.get("write_auto_subtitles"))
            wants_thumbnail = bool(options.get("write_thumbnail"))
            wants_info = bool(options.get("write_info_json"))
            subtitle_only = (
                (wants_manual_subtitles or wants_auto_subtitles)
                and not wants_video
                and not wants_thumbnail
                and not wants_info
            )
            if not any(
                (wants_video, wants_manual_subtitles, wants_auto_subtitles, wants_thumbnail, wants_info)
            ) and not options.get("preview_only"):
                return None

            item_id = str(captured_payload.get("id") or external_id)
            cover_url = self._cover_from_post(captured_payload, video)
            entry: dict[str, Any] = {
                "id": item_id,
                "title": str(captured_payload.get("desc") or item_id),
                "uploader": str(
                    (captured_payload.get("author") or {}).get("uniqueId")
                    if isinstance(captured_payload.get("author"), Mapping)
                    else ""
                )
                or None,
                "description": str(captured_payload.get("desc") or "") or None,
                "webpage_url": url,
                "extractor": "tiktok_browser_direct",
                "thumbnail": cover_url,
                "subtitles": {
                    str(item["language"]): [{}]
                    for item in subtitles
                    if not item["auto"]
                },
                "automatic_captions": {
                    str(item["language"]): [{}]
                    for item in subtitles
                    if item["auto"]
                },
            }
            if options.get("preview_only"):
                return entry

            item_dir = os.path.join(media_dir, item_id)
            await asyncio.to_thread(os.makedirs, item_dir, exist_ok=True)
            headers = {"Referer": url, "Accept": "*/*"}
            files: list[str] = []

            async def save_url(source_url: str, filename: str) -> bool:
                response = await context.request.get(source_url, headers=headers, timeout=60_000)
                if not response.ok:
                    self._progress(ctx, f"[tiktok_browser] 媒体响应失败 HTTP {response.status}")
                    return False
                body = await response.body()
                if not body:
                    return False
                await asyncio.to_thread(
                    _write_binary_file,
                    os.path.join(item_dir, filename),
                    body,
                )
                files.append(filename)
                return True

            if wants_video and video_url:
                if video_source in {"public_playback", "observed_public_playback"}:
                    self._progress(
                        ctx,
                        "[tiktok_browser] 使用平台公开播放流；若该流含水印将保持原样，不执行去水印处理",
                    )
                else:
                    self._progress(
                        ctx,
                        "[tiktok_browser] 平台未公开独立播放流，使用可用公开下载地址",
                    )
                self._progress(ctx, "[tiktok_browser] 已获取公开 CDN 视频地址，开始保存视频")
                await save_url(video_url, f"{item_id}.mp4")

            primary = str(options.get("subtitle_primary_lang") or "").strip()
            secondary = str(options.get("subtitle_secondary_lang") or "").strip()
            if primary or "subtitle_primary_lang" in options:
                selected_languages = [primary]
                if secondary and secondary.casefold() not in {"none", "无", "null"}:
                    selected_languages.append(secondary)
                patterns = [item.casefold() for item in selected_languages if item]
            else:
                patterns = [
                    item.strip().casefold()
                    for item in str(options.get("subtitle_langs") or "").split(",")
                    if item.strip()
                ]
            selected_subtitles: list[dict[str, Any]] = []
            for subtitle in subtitles:
                language = str(subtitle["language"])
                normalized = language.casefold()
                if patterns and not any(
                    normalized == pattern or normalized.startswith(pattern.rstrip(".*"))
                    for pattern in patterns
                ):
                    continue
                if subtitle["auto"] and not wants_auto_subtitles:
                    continue
                if not subtitle["auto"] and not wants_manual_subtitles:
                    continue
                selected_subtitles.append(subtitle)

            # TikTok frequently exposes one speech-recognition track as
            # ``und`` (unknown language) even when the app visibly renders
            # captions.  Older callers send the compatibility default
            # ``zh.*,en.*`` and only enable author subtitles, which silently
            # filtered that sole usable track out.  If there is no selected
            # track, make the fallback explicit in the progress log and use
            # the only public track.  This never invents captions or a
            # language; it only consumes the URL returned by TikTok itself.
            if not selected_subtitles and subtitles and wants_subtitles:
                candidates = subtitles
                if not wants_manual_subtitles and not wants_auto_subtitles:
                    candidates = []
                elif wants_manual_subtitles and not wants_auto_subtitles:
                    manual = [item for item in subtitles if not item["auto"]]
                    candidates = manual or subtitles
                if candidates:
                    selected_subtitles = candidates
                    if any(item["auto"] for item in selected_subtitles):
                        self._progress(
                            ctx,
                            "[tiktok_browser] 未找到人工字幕，改用平台公开自动字幕轨道",
                        )
                    elif any(str(item["language"]).casefold() == "und" for item in selected_subtitles):
                        self._progress(
                            ctx,
                            "[tiktok_browser] 未匹配语言过滤，使用平台唯一公开字幕轨道 und",
                        )

            for subtitle in selected_subtitles:
                language = str(subtitle["language"])
                suffix = "auto" if subtitle["auto"] else "manual"
                filename = f"{item_id}.{language}.{suffix}.vtt"
                await save_url(str(subtitle["url"]), filename)

            if wants_thumbnail and cover_url:
                public_cover = self._public_media_url(cover_url)
                if public_cover:
                    await save_url(public_cover, f"{item_id}.jpg")

            if wants_info:
                info_path = os.path.join(item_dir, f"{item_id}.info.json")
                await asyncio.to_thread(
                    _write_json_file,
                    info_path,
                    {
                        **dict(captured),
                        "extractor": "tiktok_browser_direct",
                        "webpage_url": url,
                        "sio_media_source": "tiktok_public_browser_payload",
                    },
                )
                files.append(os.path.basename(info_path))

            if not files:
                if subtitle_only:
                    available = ", ".join(
                        sorted({str(item["language"]) for item in subtitles})
                    )
                    entry["_sio_empty_reason"] = (
                        "TikTok 公开页未提供所选字幕轨道"
                        + (f"；当前公开语种：{available}" if available else "")
                        + "。已停止 yt-dlp 网页解析回退，避免重复触发相同错误。"
                    )
                    self._progress(ctx, str(entry["_sio_empty_reason"]))
                    return entry
                return None
            self._progress(ctx, f"[tiktok_browser] 已保存 {len(files)} 个公开资源")
            return entry
        finally:
            if context is not None:
                await self._dispose_context(context, page)

    max_action_delay = 4.0

    async def _login_if_configured(self, page: Page, ctx: AdapterCallContext) -> bool:
        await page.goto(
            "https://www.tiktok.com/login/phone-or-email/email",
            wait_until="domcontentloaded",
            timeout=self.page_load_timeout_ms,
        )
        await page.locator("input[name='username'], input[autocomplete='username']").first.fill(
            str(ctx.config.get("username", ""))
        )
        await page.locator("input[type='password']").first.fill(str(ctx.config.get("password", "")))
        await page.locator("button[type='submit'], button[data-e2e='login-button']").first.click()
        await page.wait_for_timeout(3000)
        challenge = page.locator(
            "iframe[src*='captcha'], [class*='captcha'], [id*='captcha']"
        ).first
        if "login" in page.url.lower() or await challenge.is_visible(timeout=500):
            raise LoginRequiredError("TikTok", "登录需要验证码、2FA 或其他人工验证")
        return True

    def _session_configured(self, ctx: AdapterCallContext) -> bool:
        """True when a login session/cookie is present in the call context.

        Distinguishes a *real* login wall (no credential configured, so retrying
        is futile) from a transient anti-bot challenge served to an already
        authenticated browser, which a retry can clear.
        """
        cfg = ctx.config if ctx is not None else {}
        return bool(cfg.get("storage_state_json") or cfg.get("cookies_netscape"))

    def _raise_profile_login_wall(self, ctx: AdapterCallContext, detail: str) -> None:
        if self._session_configured(ctx):
            # A session IS configured, so the wall is almost certainly TikTok's
            # intermittent anti-bot challenge rather than a missing credential.
            # Mark it retryable so the run's existing backoff/retry budget
            # (platform_request_max_attempts) can self-heal it instead of
            # permanently failing the account.
            raise TransientAdapterError(
                "TikTok 已配置登录态但被反爬墙临时拦截，将按可重试策略自动重试"
            )
        raise LoginRequiredError("TikTok", detail)

    def _raise_analytics_login_wall(self, ctx: AdapterCallContext, detail: str) -> None:
        if self._session_configured(ctx):
            raise TransientAdapterError(
                "TikTok anti-bot wall while a session is configured; retrying is allowed"
            )
        raise LoginRequiredError("TikTok", detail)

    def _raise_login_wall(self, ctx: AdapterCallContext, detail: str) -> None:
        """Backward-compatible alias for callers that used the old helper."""
        self._raise_profile_login_wall(ctx, detail)

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        """Navigate to the profile page and extract account info."""
        username = locator.lstrip("@")
        if not username:
            raise AdapterContractError(f"cannot extract username from locator: {locator}")

        url = TIKTOK_PROFILE_URL.format(username=username)
        context = None
        page: Page | None = None
        try:
            # Intercept SIGI_STATE or __UNIVERSAL_DATA_FOR_REHYDRATION__
            profile_data: dict[str, Any] | None = None

            async def _capture(response: Any) -> None:
                nonlocal profile_data
                if profile_data is not None:
                    return
                resp_url = response.url
                if "/api/user/detail" in resp_url or "/api/post/item_list" in resp_url:
                    try:
                        data = await response.json()
                        if "userInfo" in data:
                            profile_data = data["userInfo"]
                    except Exception:
                        pass

            context, page = await self._navigate(
                ctx,
                url,
                wait_until="domcontentloaded",
                timeout=self.page_load_timeout_ms,
                response_handler=_capture,
            )
            await self._polite_delay(2.0)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "TikTok")

            # Try to extract from embedded JSON (SIGI_STATE).
            display_name = ""
            avatar_url = None
            description = None
            follower_count = None

            if profile_data:
                user = profile_data.get("user", {})
                display_name = user.get("nickname", "")
                avatar_url = user.get("avatarLarger") or user.get("avatarMedium")
                description = user.get("signature") or None
                stats = profile_data.get("stats", {})
                follower_count = stats.get("followerCount")

            # Fallback: DOM extraction.
            if not display_name:
                try:
                    name_el = page.locator(
                        "[data-e2e='user-title'], .tiktok-j2a19r-Span, h1[data-e2e='browse-user-nickname']"
                    ).first
                    display_name = (await name_el.inner_text()).strip()
                except Exception:
                    pass
            if not display_name:
                try:
                    # Try embedded script data
                    script_data = await page.evaluate("""() => {
                        const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                        if (el) return JSON.parse(el.textContent);
                        const sigi = document.getElementById('SIGI_STATE');
                        if (sigi) return JSON.parse(sigi.textContent);
                        return null;
                    }""")
                    if script_data:
                        user_module = script_data.get("__DEFAULT_SCOPE__", {}).get(
                            "webapp.user-detail", {}
                        )
                        user_info = user_module.get("userInfo", {})
                        user = user_info.get("user", {})
                        display_name = user.get("nickname", "")
                        avatar_url = avatar_url or user.get("avatarLarger")
                        description = description or user.get("signature") or None
                        stats = user_info.get("stats", {})
                        follower_count = follower_count or stats.get("followerCount")
                except Exception:
                    pass
            if not display_name:
                display_name = f"@{username}"

            # B: a fully blocked / anti-bot TikTok page yields neither the XHR
            # profile data nor any DOM identity, so display_name falls back to
            # the synthetic "@{username}". Treat that as a login wall (consistent
            # with fetch_account_analytics) rather than caching a shared default
            # avatar for every walled account.
            #
            # This must be a *permanent* error. Anonymous access to a walled
            # profile fails identically every time, so retrying spends the whole
            # budget (3 attempts x ~41s = ~2m53s per account, every scheduled
            # sync) to arrive at the same wall, and reports a useless
            # "retry_exhausted" instead of the actionable "configure a cookie".
            if is_anti_bot_shell_profile(
                profile_data or None, display_name, synthetic_names=(f"@{username}",)
            ):
                self._raise_profile_login_wall(
                    ctx, "公开页未返回账号资料（反爬/未登录拦截），需配置登录态 cookie"
                )

            # C: only attempt a DOM avatar fallback when the authoritative XHR
            # actually returned data. On a walled page (profile_data is None) we
            # must NOT grab the page's default grey avatar. The selector is also
            # tightened to the real avatar containers (no broad [class*='avatar']).
            if not avatar_url and profile_data is not None:
                try:
                    img_el = page.locator(
                        "[data-e2e='browse-user-avatar'] img, .tiktok-1zpj2q-ImgAvatar img"
                    ).first
                    avatar_url = await img_el.get_attribute("src")
                except Exception:
                    pass

            # The embedded JSON frequently omits the bio ("signature") — fall
            # back to the rendered bio element so the account signature is not
            # silently lost.
            if not description:
                try:
                    bio_el = page.locator(
                        "[data-e2e='user-bio'], [class*='bio'], .user-bio, span.bio-text"
                    ).first
                    bio_text = (await bio_el.inner_text()).strip()
                    if bio_text:
                        description = bio_text
                except Exception:
                    pass

            return PlatformAccountData(
                external_id=username,
                username=username,
                display_name=display_name,
                profile_url=url,
                avatar_url=avatar_url,
                description=description,
                country=None,
                language="en",
                is_verified=None,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={
                    "method": "browser_scrape",
                    "locator": locator,
                    "follower_count": follower_count,
                },
            )
        except Exception as exc:
            reraise_if_terminal(exc)
            raise TransientAdapterError(
                f"browser scrape failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if context is not None:
                await self._dispose_context(context, page)

    async def fetch_account(self, ctx: AdapterCallContext, external_id: str) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        """Extract follower/like counts from the profile page."""
        username = external_id.lstrip("@")
        url = TIKTOK_PROFILE_URL.format(username=username)
        context = None
        page: Page | None = None
        try:
            context, page = await self._navigate(
                ctx,
                url,
                wait_until="domcontentloaded",
                timeout=self.page_load_timeout_ms,
            )
            await self._polite_delay(2.0)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "TikTok")

            follower_count = None
            like_count = None
            video_count = None

            # Try embedded JSON data.
            try:
                script_data = await page.evaluate("""() => {
                    const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (el) return JSON.parse(el.textContent);
                    const sigi = document.getElementById('SIGI_STATE');
                    if (sigi) return JSON.parse(sigi.textContent);
                    return null;
                }""")
                if script_data:
                    user_module = script_data.get("__DEFAULT_SCOPE__", {}).get(
                        "webapp.user-detail", {}
                    )
                    stats = user_module.get("userInfo", {}).get("stats", {})
                    follower_count = stats.get("followerCount")
                    like_count = stats.get("heartCount")
                    video_count = stats.get("videoCount")
            except Exception:
                pass

            # Fallback: DOM.
            if follower_count is None:
                try:
                    el = page.locator("[data-e2e='followers-count']").first
                    follower_count = self._parse_count(await el.inner_text())
                except Exception:
                    pass
            if like_count is None:
                try:
                    el = page.locator("[data-e2e='likes-count']").first
                    like_count = self._parse_count(await el.inner_text())
                except Exception:
                    pass

            metrics: dict[str, int | float | None] = {
                "follower_count": follower_count,
                "total_like_count": like_count,
                "video_count": video_count,
            }
            unavailable = tuple(k for k, v in metrics.items() if v is None)
            extraction_failed = (
                follower_count is None and like_count is None and video_count is None
            )
            if extraction_failed:
                # TikTok served a logged-out / anti-bot limited page: the
                # rehydration JSON and the count DOM elements are both absent.
                # Surface the wall explicitly instead of silently returning an
                # all-None metrics object that downstream code can only label
                # with a vague "指标提取失败". Permanent, not retryable — see the
                # matching branch in ``resolve_account``.
                self._raise_analytics_login_wall(
                    ctx, "公开页未返回账号指标（反爬/未登录拦截），需配置登录态 cookie"
                )
            return PlatformMetricsData(
                external_id=username,
                captured_at=ctx.observed_at,
                metrics=metrics,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=unavailable,
                metadata={"method": "browser_scrape", "analytics_fetched": True},
            )
        finally:
            if context is not None:
                await self._dispose_context(context, page)

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        """Scrape the video list from the profile page."""
        username = external_account_id.lstrip("@")
        try:
            offset = int(cursor) if cursor else 0
        except (TypeError, ValueError) as exc:
            raise AdapterContractError("TikTok browser cursor must be numeric") from exc
        if offset < 0:
            raise AdapterContractError("TikTok browser cursor cannot be negative")
        requested_page_size, scroll_rounds = _profile_pagination_window(
            offset, page_size
        )
        url = TIKTOK_PROFILE_URL.format(username=username)
        context = None
        page: Page | None = None
        try:
            # The profile grid is backed by a public post-list response that
            # contains the authoritative caption, timestamp, stats and cover.
            # The rendered anchor text is usually only the view-count label;
            # treating it as a title produced rows such as "6101" and "31.7K".
            post_data: dict[str, dict[str, Any]] = {}
            api_has_more = False

            async def _capture(response: Any) -> None:
                nonlocal api_has_more
                if "/api/post/item_list" not in response.url:
                    return
                try:
                    payload = await response.json()
                    if not isinstance(payload, dict):
                        return
                    api_has_more = api_has_more or bool(
                        payload.get("hasMore") or payload.get("has_more")
                    )
                    raw_items = payload.get("itemList")
                    if not isinstance(raw_items, list):
                        return
                    for raw_item in raw_items:
                        if not isinstance(raw_item, dict):
                            continue
                        post_id = str(raw_item.get("id") or "")
                        if post_id:
                            post_data.setdefault(post_id, raw_item)
                except Exception:  # noqa: BLE001 - API response is best effort
                    logger.debug("TikTok post-list response could not be decoded", exc_info=True)

            context, page = await self._navigate(
                ctx,
                url,
                wait_until="domcontentloaded",
                timeout=self.page_load_timeout_ms,
                response_handler=_capture,
            )
            await self._polite_delay(2.0)
            # Anonymous-first: stop before paying for 10 scroll rounds on a page
            # that will never render the grid.
            await self._check_login_required(page, "TikTok")
            # Scroll further than the default (10×) so TikTok lazily renders more
            # of the video grid before we scrape the anchors.
            # A browser fallback has no server-side continuation token. Reopen
            # the profile, materialize the prefix for this offset, and slice the
            # local anchor list. The previous implementation ignored ``cursor``
            # and returned page one repeatedly, making every later page a set of
            # duplicates and preventing complete account ingestion.
            # The structured post response is captured during scrolling. Stop
            # as soon as the requested slice is materialized instead of paying
            # for a fixed worst-case deep-page scroll on every sync.
            target_count = offset + requested_page_size
            for _ in range(scroll_rounds):
                if len(post_data) >= target_count:
                    break
                await self._scroll_page(page, times=1, ctx=ctx)

            # TikTok can return a normal 200 profile shell with a slider
            # challenge instead of the video grid. Treating that shell as a
            # successful empty catalogue silently marks a real account as
            # complete with zero works. Surface the actionable condition and
            # let an authorized persistent browser session recover it.
            try:
                body_text = (await page.locator("body").inner_text()).casefold()
            except Exception:
                body_text = ""
            if any(
                marker in body_text
                for marker in (
                    "drag the slider",
                    "slide to fit",
                    "拖动滑块",
                    "滑动验证",
                    "拼图验证",
                )
            ):
                self._raise_profile_login_wall(
                    ctx,
                    "TikTok 返回了人机验证页面；请在已授权浏览器中完成验证后再同步",
                )

            # Prefer the structured public response whenever it was observed.
            # It remains cursor-aware because the page is re-materialized for
            # each requested offset before this slice is returned.
            if post_data:
                ordered_posts = list(post_data.values())
                items = [
                    self._post_to_content(item, username, ctx, index)
                    for index, item in enumerate(
                        ordered_posts[: offset + requested_page_size]
                    )
                ]
                page_items = items[offset : offset + requested_page_size]
                page_items = list(
                    await self._archive_profile_thumbnails(
                        context, ctx, username, page_items
                    )
                )
                has_more = api_has_more or len(ordered_posts) >= offset + requested_page_size
                return AdapterPage(
                    items=tuple(page_items),
                    next_cursor=(
                        str(offset + len(page_items))
                        if has_more and page_items
                        else None
                    ),
                )

            # The video grid renders as anchors whose href contains "/video/".
            # (Legacy selectors such as [data-e2e='user-post-item'] are no longer
            # reliable; the href-based approach works on the current DOM and on a
            # real local browser driven over CDP.)
            try:
                await page.wait_for_selector("a[href*='/video/']", timeout=12_000)
            except Exception:
                return AdapterPage(items=(), next_cursor=None)

            grid_items: list[PlatformContentData] = []
            anchors = page.locator("a[href*='/video/']")
            count = await anchors.count()

            for i in range(min(count, offset + requested_page_size)):
                try:
                    anchor = anchors.nth(i)
                    href = await anchor.get_attribute("href") or ""
                    vid_match = re.search(r"/video/(\d+)", href)
                    if not vid_match:
                        continue
                    video_id = vid_match.group(1)

                    title = ""
                    try:
                        title = (await anchor.get_attribute("aria-label") or "").strip()
                    except Exception:
                        pass
                    card_text = ""
                    try:
                        card_text = (await anchor.inner_text()).strip()
                    except Exception:
                        pass
                    candidate = title or card_text
                    title_is_count = bool(
                        re.fullmatch(
                            r"[\d.,]+\s*[KMB]?\s*(?:views?|播放|次播放)?",
                            candidate,
                            flags=re.IGNORECASE,
                        )
                    )
                    if title_is_count:
                        title = f"视频 {video_id}"
                    else:
                        title = candidate
                    if not title:
                        title = f"视频 {video_id}"

                    cover_url = None
                    try:
                        img_el = anchor.locator("img").first
                        cover_url = await img_el.get_attribute("src")
                    except Exception:
                        pass

                    # Best-effort view count from the card text (e.g. "1.2M views").
                    view_count = None
                    if title_is_count:
                        view_count = self._parse_count(candidate)
                    else:
                        vm = re.search(r"([\d.,]+\s*[KMB]?)\s*views?", card_text, re.I)
                        if vm:
                            view_count = self._parse_count(vm.group(1))

                    canonical = TIKTOK_VIDEO_URL.format(username=username, video_id=video_id)
                    grid_items.append(
                        PlatformContentData(
                            external_id=video_id or f"{username}_v{i}",
                            account_external_id=username,
                            content_type="video",
                            title=title,
                            description=None,
                            published_at=None,
                            duration_seconds=None,
                            canonical_url=canonical,
                            cover_url=cover_url,
                            language="en",
                            status="public",
                            source_kind="live",
                            provider=self.key,
                            fetched_at=ctx.observed_at,
                            metadata={
                                "method": "browser_scrape",
                                "view_count": view_count,
                                "title_source": "external_id_fallback"
                                if title_is_count or not candidate
                                else "dom_label",
                                "title_unavailable": title_is_count or not candidate,
                            },
                        )
                    )
                except Exception as exc:
                    logger.debug("skip card %d: %s", i, exc)
                    continue

            page_items = grid_items[offset : offset + requested_page_size]
            page_items = list(
                await self._archive_profile_thumbnails(
                    context, ctx, username, page_items
                )
            )
            next_cursor = (
                str(offset + requested_page_size)
                if len(grid_items) >= offset + requested_page_size
                else None
            )
            return AdapterPage(items=tuple(page_items), next_cursor=next_cursor)
        except Exception as exc:
            reraise_if_terminal(exc)
            raise TransientAdapterError(
                f"browser list_contents failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if context is not None:
                await self._dispose_context(context, page)

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        """Fetch a single video page."""
        url = f"https://www.tiktok.com/video/{external_id}"
        context = None
        page: Page | None = None
        try:
            context, page = await self._navigate(
                ctx, url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms
            )
            await self._polite_delay(1.5)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "TikTok")

            title = await page.title()
            title = title.replace(" | TikTok", "").strip()

            cover_url = None
            try:
                og_img = page.locator("meta[property='og:image']")
                cover_url = await og_img.get_attribute("content")
            except Exception:
                pass

            return PlatformContentData(
                external_id=external_id,
                account_external_id="",
                content_type="video",
                title=title or external_id,
                description=None,
                published_at=None,
                duration_seconds=None,
                canonical_url=url,
                cover_url=cover_url,
                language="en",
                status="public",
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={"method": "browser_scrape"},
            )
        finally:
            if context is not None:
                await self._dispose_context(context, page)

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        return tuple(
            PlatformMetricsData(
                external_id=eid,
                captured_at=ctx.observed_at,
                metrics={},
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=("view_count", "like_count", "comment_count", "share_count"),
                metadata={
                    "method": "browser_scrape",
                    "note": "analytics not available via browser",
                },
            )
            for eid in external_ids
        )

    @staticmethod
    def _cover_from_post(item: Mapping[str, Any], video: Mapping[str, Any]) -> str | None:
        """Return the first public cover from video or photo-post payloads.

        TikTok uses a different branch for photo/carousel posts and older
        responses sometimes put the cover directly on the item. Keeping this
        normalization here prevents a valid work from entering the database
        without a cover merely because it is not a conventional video.
        """

        def url_list(value: Any) -> str | None:
            if isinstance(value, str) and value:
                return value
            if not isinstance(value, Mapping):
                return None
            urls = value.get("urlList") or value.get("url_list")
            if isinstance(urls, list):
                for candidate in urls:
                    if isinstance(candidate, str) and candidate:
                        return candidate
            for key in ("url", "uri"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate:
                    return candidate
            return None

        for source in (item, video):
            for key in ("cover", "coverUrl", "cover_url", "originCover", "dynamicCover"):
                cover = url_list(source.get(key))
                if cover:
                    return cover

        image_post = item.get("imagePost") or item.get("image_post")
        if isinstance(image_post, Mapping):
            for key in ("imageURL", "imageUrl", "image_url", "cover"):
                cover = url_list(image_post.get(key))
                if cover:
                    return cover
            images = image_post.get("images")
            if isinstance(images, list):
                for image in images:
                    if isinstance(image, Mapping):
                        for key in ("imageURL", "imageUrl", "image_url", "cover"):
                            cover = url_list(image.get(key))
                            if cover:
                                return cover
        return None

    @staticmethod
    def _post_to_content(
        item: Mapping[str, Any],
        username: str,
        ctx: AdapterCallContext,
        index: int,
    ) -> PlatformContentData:
        post_id = str(item.get("id") or f"{username}_{index}")
        desc = str(item.get("desc") or "").strip()
        raw_video = item.get("video")
        video: Mapping[str, Any] = raw_video if isinstance(raw_video, Mapping) else {}
        raw_stats = item.get("stats")
        stats: Mapping[str, Any] = raw_stats if isinstance(raw_stats, Mapping) else {}
        if not stats and isinstance(item.get("statsV2"), dict):
            stats = item["statsV2"]

        def stat(*keys: str) -> int | None:
            for key in keys:
                raw = stats.get(key)
                if isinstance(raw, bool):
                    continue
                if isinstance(raw, (int, float)):
                    return int(raw)
                if isinstance(raw, str) and raw.strip().isdigit():
                    return int(raw)
            return None

        cover_url = TikTokBrowserAdapter._cover_from_post(item, video)

        published_at = None
        raw_create_time = item.get("createTime") or item.get("create_time")
        if raw_create_time is not None:
            try:
                published_at = datetime.fromtimestamp(float(raw_create_time), tz=UTC)
            except (TypeError, ValueError, OverflowError):
                pass

        title = desc or f"视频 {post_id}"
        return PlatformContentData(
            external_id=post_id,
            account_external_id=username,
            content_type="video",
            title=title,
            description=None,
            published_at=published_at,
            duration_seconds=video.get("duration"),
            canonical_url=TIKTOK_VIDEO_URL.format(username=username, video_id=post_id),
            cover_url=cover_url,
            language=str(item.get("textLanguage") or "en"),
            status="public",
            source_kind="live",
            provider="tiktok_browser",
            fetched_at=ctx.observed_at,
            metadata={
                "method": "browser_api_intercept",
                "view_count": stat("playCount", "play_count", "playCountV2"),
                "like_count": stat("diggCount", "likeCount", "digg_count"),
                "comment_count": stat("commentCount", "comment_count"),
                "share_count": stat("shareCount", "share_count"),
                "favorite_count": stat("collectCount", "favorite_count"),
                "title_source": "platform_caption" if desc else "external_id_fallback",
                "title_unavailable": not bool(desc),
            },
        )

    @staticmethod
    def _parse_count(text: str) -> int | None:
        """Parse '1.2M', '456K', '789' into integer."""
        text = text.strip().upper().replace(",", "")
        m = re.match(r"([\d.]+)\s*([KM]?)", text)
        if not m:
            return None
        num = float(m.group(1))
        suffix = m.group(2)
        if suffix == "K":
            return int(num * 1_000)
        if suffix == "M":
            return int(num * 1_000_000)
        if suffix == "B":
            return int(num * 1_000_000_000)
        return int(num)
