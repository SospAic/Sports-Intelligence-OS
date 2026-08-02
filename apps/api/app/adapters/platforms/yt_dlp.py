# ruff: noqa: E501, I001
"""yt-dlp universal adapter (command-line, no browser required).

This adapter extracts **public** metadata from YouTube / TikTok / Douyin by
shelling out to `yt-dlp` — the mature, community-maintained parser of each
platform's private InnerTube / web JSON. Compared with the browser-simulation
adapters it:

* needs no Chromium / Playwright (lighter, faster, no fingerprint wall);
* returns *exact* view/like/comment counts, duration, description, tags,
  structured channel ids and an exact publish timestamp — instead of the
  approximate, text-scraped values the browser adapter produced;

and it degrades gracefully: whenever yt-dlp cannot extract the data (e.g.
Douyin is essentially unsupported and TikTok occasionally needs a browser
signature), the adapter transparently delegates to the platform's
browser-simulation adapter so no data is lost.

All data is publicly available and fetched anonymously, matching the project's
"公开渠道优先" acquisition baseline. No login, CAPTCHA bypass, or access-limit
circumvention is used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterDescriptor,
    AdapterHealth,
    AdapterPage,
    PlatformAccountData,
    PlatformAdapter,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)

# Generous timeout: a YouTube channel playlist can take a while to resolve all
# per-video metadata, and we never want a hung subprocess to block a worker.
YTDLP_TIMEOUT_SECONDS = 180


def _build_descriptor(key: str, name: str) -> AdapterDescriptor:
    return AdapterDescriptor(
        key=key,
        name=name,
        implementation_status="implemented",
        capabilities={
            AdapterCapability.PUBLIC_PROFILE: True,
            AdapterCapability.ACCOUNT_ANALYTICS: True,
            AdapterCapability.CONTENT_LIST: True,
            # yt-dlp returns exact view/like/comment/share counts, so we now
            # genuinely support per-content analytics (the browser adapter did not).
            AdapterCapability.CONTENT_ANALYTICS: True,
            AdapterCapability.TRAFFIC_SOURCES: False,
            AdapterCapability.RETENTION: False,
            AdapterCapability.REVENUE: False,
            AdapterCapability.COMMENTS: False,
            AdapterCapability.SEARCH_TERMS: False,
        },
        config_fields=(),
        source_kinds=frozenset({"live"}),
    )


class YtDlpAdapter(PlatformAdapter):
    """Base adapter that drives ``yt-dlp`` and falls back to a browser adapter.

    Subclasses set ``platform`` and the URL builders. The adapter is stateless
    except for a small per-run cache of per-video metrics (populated by
    ``list_contents`` and consumed by ``fetch_content_analytics``).
    """

    #: one of "youtube", "tiktok", "douyin"
    platform: str = "youtube"

    def __init__(self) -> None:
        self._fb: PlatformAdapter | None = None
        self._cache: dict[str, dict[str, int]] = {}

    # -- URL builders -------------------------------------------------------

    def _normalize_handle(self, locator: str) -> str:
        h = (locator or "").strip().split("?")[0].split("#")[0]
        if not h:
            return ""
        if "@" in h:
            h = h.split("@")[-1]
        elif "/" in h:
            h = h.rstrip("/").split("/")[-1]
        return h.strip("@").strip()

    def _account_url(self, handle: str) -> str:
        if self.platform == "youtube":
            return f"https://www.youtube.com/@{handle}"
        if self.platform == "tiktok":
            return f"https://www.tiktok.com/@{handle}"
        return f"https://www.douyin.com/@{handle}"

    def _videos_url(self, handle: str) -> str:
        if self.platform == "youtube":
            return f"https://www.youtube.com/@{handle}/videos"
        # TikTok / Douyin expose the video grid on the profile itself.
        return self._account_url(handle)

    def _canonical_for(self, video_id: str, handle: str) -> str:
        if self.platform == "youtube":
            return f"https://www.youtube.com/watch?v={video_id}"
        if self.platform == "tiktok":
            return f"https://www.tiktok.com/@{handle}/video/{video_id}"
        return f"https://www.douyin.com/video/{video_id}"

    # -- fallback browser adapter ------------------------------------------

    def _fallback(self) -> PlatformAdapter:
        if self._fb is not None:
            return self._fb
        if self.platform == "youtube":
            from app.adapters.platforms.youtube_browser import YouTubeBrowserAdapter

            self._fb = YouTubeBrowserAdapter()
        elif self.platform == "tiktok":
            from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter

            self._fb = TikTokBrowserAdapter()
        else:
            from app.adapters.platforms.douyin_browser import DouyinBrowserAdapter

            self._fb = DouyinBrowserAdapter()
        return self._fb

    # -- yt-dlp process ----------------------------------------------------

    async def _run_yt_dlp(
        self,
        url: str,
        *,
        playlist_start: int | None = None,
        playlist_end: int | None = None,
        dateafter: str | None = None,
        datebefore: str | None = None,
        extra_args: Mapping[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Run yt-dlp and return ``(parsed_entries, stderr_text)``.

        Raises :class:`TransientAdapterError` only on hard failures with no
        usable output; a query that simply yields zero entries returns empty
        lists so the caller can decide whether to fall back.

        ``playlist_start`` / ``playlist_end`` drive windowed pagination so a
        single sync can page past yt-dlp's default 50-item ceiling. ``dateafter``
        / ``datebefore`` are ``YYYYMMDD`` strings forwarded to yt-dlp's date
        filter. ``extra_args`` is a flat passthrough of additional yt-dlp
        options (``{"match_filter": "...", "geo_bypass": True}``) operator-tuned
        via the workspace's centralised ``sync_settings`` policy.
        """
        cmd: list[str] = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-json",
            "--skip-download",
            "--no-warnings",
            "--no-progress",
            "--ignore-errors",
        ]
        if playlist_start is not None:
            cmd += ["--playlist-start", str(playlist_start)]
        if playlist_end is not None:
            cmd += ["--playlist-end", str(playlist_end)]
        if dateafter:
            cmd += ["--dateafter", dateafter]
        if datebefore:
            cmd += ["--datebefore", datebefore]
        if extra_args:
            for key, value in extra_args.items():
                if value is None or value is False:
                    continue
                flag = f"--{key.replace('_', '-')}"
                if value is True:
                    cmd.append(flag)
                else:
                    cmd += [flag, str(value)]
        cmd.append(url)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=YTDLP_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            raise TransientAdapterError("yt-dlp subprocess timed out") from exc

        err_text = err.decode("utf-8", "replace") if err else ""
        if proc.returncode not in (0, None) and not out:
            raise TransientAdapterError(f"yt-dlp failed: {err_text[:500]}")

        entries: list[dict[str, Any]] = []
        if out:
            for line in out.decode("utf-8", "replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    entries.append(obj)
        return entries, err_text

    async def _run_yt_dlp_single(
        self, url: str, *, playlist_end: int = 1
    ) -> tuple[dict[str, Any], str]:
        """Run yt-dlp with ``--dump-single-json`` and return the parsed object.

        The single playlist/JSON object carries the **channel-level** metadata
        (``channel_follower_count``, ``channel_id``, ``avatar``/``thumbnails``,
        ``playlist_count``) that the per-video line-delimited output omits, so
        account resolution and analytics can avoid the browser entirely. The
        ``entries`` array is ignored here (see :meth:`list_contents`).
        """
        cmd: list[str] = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--no-progress",
            "--ignore-errors",
            "--playlist-end",
            str(playlist_end),
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=YTDLP_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            raise TransientAdapterError("yt-dlp single-json timed out") from exc

        err_text = err.decode("utf-8", "replace") if err else ""
        if proc.returncode not in (0, None) and not out:
            raise TransientAdapterError(f"yt-dlp failed: {err_text[:500]}")
        if not out:
            return {}, err_text
        try:
            return json.loads(out.decode("utf-8", "replace")), err_text
        except json.JSONDecodeError as exc:
            raise TransientAdapterError(f"yt-dlp returned invalid JSON: {exc}") from exc

    # -- shared field extractors -------------------------------------------

    @staticmethod
    def _extract_thumbnail(entry: Mapping[str, Any]) -> str | None:
        thumb = entry.get("thumbnail")
        if isinstance(thumb, str) and thumb:
            return thumb
        if isinstance(thumb, dict) and thumb.get("url"):
            return str(thumb["url"])
        thumbs = entry.get("thumbnails")
        if isinstance(thumbs, list):
            best: str | None = None
            for th in thumbs:
                if isinstance(th, dict) and th.get("url"):
                    best = str(th["url"])
                    if th.get("width") and int(th["width"]) >= 300:
                        return str(th["url"])
            return best
        return None

    @staticmethod
    def _parse_timestamp(entry: Mapping[str, Any]) -> datetime | None:
        ts = entry.get("timestamp")
        if ts is not None:
            try:
                return datetime.fromtimestamp(float(ts), tz=UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        upload = entry.get("upload_date")
        if isinstance(upload, str) and len(upload) == 8:
            try:
                return datetime.strptime(upload, "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                pass
        return None

    @staticmethod
    def _metrics_from_entry(entry: Mapping[str, Any]) -> dict[str, int]:
        raw = {
            "view_count": entry.get("view_count"),
            "like_count": entry.get("like_count"),
            "comment_count": entry.get("comment_count"),
            "share_count": entry.get("repost_count"),
        }
        return {k: int(v) for k, v in raw.items() if isinstance(v, (int, float))}

    def _entry_to_content(
        self, entry: Mapping[str, Any], handle: str, ctx: AdapterCallContext
    ) -> PlatformContentData:
        video_id = str(entry.get("id") or "")
        title = (entry.get("title") or "").strip()
        url = entry.get("webpage_url") or entry.get("url")
        if not url:
            url = self._canonical_for(video_id, handle)
        cover = self._extract_thumbnail(entry)
        duration = entry.get("duration")
        published = self._parse_timestamp(entry)
        metrics = self._metrics_from_entry(entry)
        language = (
            "en"
            if self.platform == "youtube"
            else ("zh" if self.platform == "douyin" else None)
        )
        return PlatformContentData(
            external_id=video_id or f"{handle}_{id(entry)}",
            account_external_id=handle,
            content_type="video",
            title=title or f"Video {video_id}",
            description=entry.get("description"),
            published_at=published,
            duration_seconds=float(duration) if duration is not None else None,
            canonical_url=url,
            cover_url=cover,
            language=language,
            status="public",
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={
                "method": "yt_dlp",
                **{f"yt_{k}": v for k, v in metrics.items()},
            },
        )

    # -- PlatformAdapter contract -----------------------------------------

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        # yt-dlp works anonymously; browser fallback carries its own validation.
        return None

    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        handle = self._normalize_handle(locator)
        try:
            data, _ = await self._run_yt_dlp_single(self._account_url(handle), playlist_end=1)
        except TransientAdapterError:
            data = {}
        display = data.get("uploader") or data.get("channel")
        if not display:
            logger.info(
                "yt_dlp account extraction failed for %s/%s; using browser fallback",
                self.platform,
                handle,
            )
            return await self._fallback().resolve_account(ctx, locator)

        avatar = self._extract_thumbnail(data)
        channel_id = data.get("channel_id") or data.get("uploader_id")
        language = (
            "en"
            if self.platform == "youtube"
            else ("zh" if self.platform == "douyin" else None)
        )
        return PlatformAccountData(
            external_id=handle,
            username=handle,
            display_name=display,
            profile_url=self._account_url(handle),
            avatar_url=avatar,
            description=data.get("description"),
            country=None,
            language=language,
            is_verified=None,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={"method": "yt_dlp", "channel_id": channel_id},
        )

    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        handle = self._normalize_handle(external_id)
        try:
            data, _ = await self._run_yt_dlp_single(self._account_url(handle), playlist_end=1)
        except TransientAdapterError:
            data = {}
        follower = data.get("channel_follower_count") or data.get("subscriber_count")
        if follower is None:
            logger.info(
                "yt_dlp follower extraction failed for %s/%s; using browser fallback",
                self.platform,
                handle,
            )
            return await self._fallback().fetch_account_analytics(ctx, external_id)

        playlist_count = data.get("playlist_count")
        metrics: dict[str, int | None] = {
            "follower_count": int(follower),
            "video_count": int(playlist_count) if playlist_count is not None else None,
            "total_view_count": None,
        }
        unavailable = tuple(k for k, v in metrics.items() if v is None)
        return PlatformMetricsData(
            external_id=handle,
            captured_at=ctx.observed_at,
            metrics=metrics,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            unavailable_metrics=unavailable,
            metadata={"method": "yt_dlp"},
        )

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        handle = self._normalize_handle(external_account_id)
        self._cache.clear()

        cfg = ctx.config or {}
        yt_cfg = cfg.get("yt_dlp") if isinstance(cfg.get("yt_dlp"), dict) else {}
        dateafter = yt_cfg.get("dateafter") if isinstance(yt_cfg, dict) else None
        datebefore = yt_cfg.get("datebefore") if isinstance(yt_cfg, dict) else None
        max_items = yt_cfg.get("max_items") if isinstance(yt_cfg, dict) else None
        extra_args = yt_cfg.get("extra_args") if isinstance(yt_cfg, dict) else None
        if published_after is not None and not dateafter:
            dateafter = published_after.strftime("%Y%m%d")

        offset = int(cursor) if cursor and str(cursor).isdigit() else 0
        window = page_size
        if max_items is not None:
            window = min(window, max(1, int(max_items) - offset))
            if window <= 0:
                return AdapterPage(items=(), next_cursor=None)

        playlist_start = offset + 1
        playlist_end = offset + window
        try:
            entries, _ = await self._run_yt_dlp(
                self._videos_url(handle),
                playlist_start=playlist_start,
                playlist_end=playlist_end,
                dateafter=dateafter,
                datebefore=datebefore,
                extra_args=extra_args if isinstance(extra_args, dict) else None,
            )
        except TransientAdapterError as exc:
            logger.warning(
                "yt_dlp list_contents failed for %s/%s: %s; browser fallback",
                self.platform,
                handle,
                exc,
            )
            # Only fall back on the first page. A failure while paging deeper is
            # just the end of the playlist — returning an empty page avoids a
            # spurious browser re-fetch that would restart from the beginning.
            if cursor is None:
                return await self._fallback().list_contents(
                    ctx,
                    external_account_id,
                    published_after=published_after,
                    cursor=cursor,
                    page_size=page_size,
                )
            return AdapterPage(items=(), next_cursor=None)
        if not entries:
            if cursor is None:
                logger.warning(
                    "yt_dlp returned no entries for %s/%s; browser fallback",
                    self.platform,
                    handle,
                )
                return await self._fallback().list_contents(
                    ctx,
                    external_account_id,
                    published_after=published_after,
                    cursor=cursor,
                    page_size=page_size,
                )
            # Trailing page during pagination: end of playlist, not an error.
            return AdapterPage(items=(), next_cursor=None)

        items: list[PlatformContentData] = []
        for entry in entries[:window]:
            content = self._entry_to_content(entry, handle, ctx)
            items.append(content)
            self._cache[content.external_id] = self._metrics_from_entry(entry)

        fetched = len(items)
        next_offset = offset + fetched
        # Continue paging only when a full window was returned (more may exist).
        # When a per-account / config cap is in effect, stop exactly at the cap
        # so we never emit a dangling cursor that triggers an extra empty page.
        will_continue = fetched >= window
        if max_items is not None and next_offset >= int(max_items):
            will_continue = False
        next_cursor = str(next_offset) if will_continue else None
        return AdapterPage(items=tuple(items), next_cursor=next_cursor)

    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData:
        if self.platform == "youtube":
            url = f"https://www.youtube.com/watch?v={external_id}"
            try:
                entries, _ = await self._run_yt_dlp(url)
            except TransientAdapterError:
                entries = []
            if entries:
                return self._entry_to_content(entries[0], "", ctx)
        return await self._fallback().fetch_content(ctx, external_id)

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        results: list[PlatformMetricsData] = []
        for eid in external_ids:
            cached = self._cache.get(eid)
            if cached:
                results.append(
                    PlatformMetricsData(
                        external_id=eid,
                        captured_at=ctx.observed_at,
                        metrics=cached,
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=(),
                        metadata={"method": "yt_dlp"},
                    )
                )
            else:
                results.append(
                    PlatformMetricsData(
                        external_id=eid,
                        captured_at=ctx.observed_at,
                        metrics={},
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=(
                            "view_count",
                            "like_count",
                            "comment_count",
                            "share_count",
                        ),
                        metadata={"method": "yt_dlp", "note": "not in last list fetch"},
                    )
                )
        return tuple(results)

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "yt_dlp",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0:
                return AdapterHealth(
                    status="ok",
                    checked_at=ctx.observed_at,
                    detail="yt-dlp available (browser fallback ready)",
                )
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return AdapterHealth(
                status="unavailable",
                checked_at=ctx.observed_at,
                detail=f"yt-dlp unavailable: {exc}",
            )
        return AdapterHealth(
            status="unavailable",
            checked_at=ctx.observed_at,
            detail="yt-dlp exited non-zero",
        )

    async def aclose(self) -> None:
        if self._fb is not None:
            try:
                await self._fb.aclose()
            except Exception:  # noqa: BLE001, S110
                pass
        self._fb = None
        self._cache.clear()


class YouTubeYtDlpAdapter(YtDlpAdapter):
    platform = "youtube"
    descriptor = _build_descriptor("youtube_ytdlp", "YouTube（yt-dlp）")


class TikTokYtDlpAdapter(YtDlpAdapter):
    platform = "tiktok"
    descriptor = _build_descriptor("tiktok_ytdlp", "TikTok（yt-dlp）")


class DouyinYtDlpAdapter(YtDlpAdapter):
    platform = "douyin"
    descriptor = _build_descriptor("douyin_ytdlp", "抖音（yt-dlp）")
