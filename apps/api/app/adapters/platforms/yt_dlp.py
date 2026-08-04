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
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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

# yt-dlp's built-in network retry count. We set it explicitly (rather than
# relying on yt-dlp's own default) so the value is visible and operator-tunable,
# and so account-data and content-list invocations share one policy. This is the
# *only* retry mechanism we use for yt-dlp — we deliberately do NOT wrap yt-dlp
# calls in a bespoke retry loop; yt-dlp already retries internally on transient
# network errors, and a second layer would just multiply latency and platform
# request volume (raising anti-bot risk). Operators can override it per workspace
# via ``sync_settings.yt_dlp.retries``; anything not set falls back to this.
YTDLP_DEFAULT_RETRIES = 10

# Structured ``sync_settings.yt_dlp`` fields that map to a yt-dlp CLI flag.
# ``dateafter`` / ``datebefore`` / ``playlist_start`` are handled by the sync
# executor's windowing (not as raw flags here), and ``extra_args`` is a
# free-form passthrough, so neither appears in this table. Each entry is
# ``(field_name, cli_flag_without_dashes, kind)`` where kind is one of
# "bool" (flag present only when True), "int" (``--flag N``) or "str".
YTDLP_FIELD_SPECS: tuple[tuple[str, str, str], ...] = (
    ("daterange", "daterange", "str"),
    ("playlist_items", "playlist-items", "str"),
    ("playlist_reverse", "playlist-reverse", "bool"),
    ("playlist_random", "playlist-random", "bool"),
    ("no_playlist", "no-playlist", "bool"),
    ("flat_playlist", "flat-playlist", "bool"),
    ("sort", "sort", "str"),
    ("match_filter", "match-filter", "str"),
    ("match_title", "match-title", "str"),
    ("reject_title", "reject-title", "str"),
    ("age_limit", "age-limit", "int"),
    ("min_duration", "min-duration", "int"),
    ("max_duration", "max-duration", "int"),
    ("min_filesize", "min-filesize", "str"),
    ("max_filesize", "max-filesize", "str"),
    ("proxy", "proxy", "str"),
    ("socket_timeout", "socket-timeout", "int"),
    ("retries", "retries", "int"),
    ("fragment_retries", "fragment-retries", "int"),
    ("sleep_interval", "sleep-interval", "int"),
    ("max_sleep_interval", "max-sleep-interval", "int"),
    ("sleep_requests", "sleep-requests", "int"),
    ("limit_rate", "limit-rate", "str"),
    ("geo_bypass", "geo-bypass", "bool"),
    ("geo_bypass_country", "geo-bypass-country", "str"),
    ("geo_verification_proxy", "geo-verification-proxy", "str"),
    ("ignore_errors", "ignore-errors", "bool"),
    ("no_warnings", "no-warnings", "bool"),
)
YTDLP_SPEC_KEYS: frozenset[str] = frozenset(spec[0] for spec in YTDLP_FIELD_SPECS)


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
            # Best-effort: yt-dlp can extract comments for YouTube / TikTok /
            # Douyin to varying degrees; on failure we return [] (UI shows the
            # required acquisition condition rather than a fabricated count).
            AdapterCapability.COMMENTS: True,
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
        # Per-run memo of ``_run_yt_dlp_single`` results, keyed by URL. A single
        # sync run calls ``resolve_account`` and ``fetch_account_analytics`` on the
        # same channel URL; without this, yt-dlp is launched twice for the
        # identical channel object — a needless full subprocess per account. The
        # cache lives only for the adapter instance (one sync run / worker
        # process), so it never serves stale data across accounts or runs.
        self._single_json_cache: dict[str, tuple[dict[str, Any], str]] = {}
        # Per-run memo of browser-adapter results. ``resolve_account`` and
        # ``fetch_account_analytics`` both fall back to the browser for the same
        # handle; without this the (very slow) Playwright browser would be
        # launched twice per account. Same lifecycle as ``_single_json_cache``.
        self._browser_account_cache: dict[str, Any] = {}
        self._browser_analytics_cache: dict[str, Any] = {}

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

    @staticmethod
    def _safe_dir(name: str) -> str:
        """Turn an arbitrary handle into a filesystem-safe directory name."""
        cleaned = re.sub(r"[^A-Za-z0-9_@.-]", "_", name or "unknown")
        return cleaned[:120] or "unknown"

    @staticmethod
    def _any_download_enabled(download: Mapping[str, Any] | None) -> bool:
        if not isinstance(download, dict):
            return False
        return bool(
            download.get("write_thumbnail")
            or download.get("write_subtitles")
            or download.get("write_auto_subtitles")
            or download.get("write_info_json")
            or download.get("download_video")
        )

    @staticmethod
    def _collect_media(
        media_root: str, media_dir: str, video_id: str
    ) -> dict[str, Any] | None:
        """Scan the per-video output dir and classify discovered files.

        Returns ``None`` when nothing was written. ``base`` is the
        workspace-relative path under ``media_root`` used by the ``/media``
        route to resolve files safely.
        """
        d = os.path.join(media_dir, video_id)
        if not os.path.isdir(d):
            return None
        try:
            base = os.path.relpath(d, media_root)
        except ValueError:
            base = video_id
        thumbnail = video = info_json = None
        subtitles: list[dict[str, str]] = []
        for fn in os.listdir(d):
            low = fn.lower()
            if low.endswith(".info.json"):
                info_json = fn
            elif low.endswith((".vtt", ".srt", ".ass", ".sbv", ".lrc")):
                lang = ""
                if fn.startswith(video_id + "."):
                    lang = fn[len(video_id) + 1 : -len(os.path.splitext(fn)[1])]
                subtitles.append({"lang": lang, "file": fn})
            elif low.endswith((".mp4", ".webm", ".mkv", ".mov", ".flv", ".m4v", ".avi")):
                video = fn
            elif low.endswith((".webp", ".jpg", ".jpeg", ".png")):
                thumbnail = fn
        result: dict[str, Any] = {"base": base}
        if thumbnail:
            result["thumbnail"] = thumbnail
        if video:
            result["video"] = video
        if info_json:
            result["info_json"] = info_json
        if subtitles:
            result["subtitles"] = subtitles
        return result if (thumbnail or video or info_json or subtitles) else None

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

    async def _browser_resolve(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        cached = self._browser_account_cache.get(locator)
        if cached is None:
            cached = await self._fallback().resolve_account(ctx, locator)
            self._browser_account_cache[locator] = cached
        return cached

    async def _browser_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        cached = self._browser_analytics_cache.get(external_id)
        if cached is None:
            cached = await self._fallback().fetch_account_analytics(ctx, external_id)
            self._browser_analytics_cache[external_id] = cached
        return cached

    # -- yt-dlp process ----------------------------------------------------

    @staticmethod
    def _render_structured(yt_cfg: Mapping[str, Any]) -> list[str]:
        """Translate structured ``yt_dlp`` fields into yt-dlp CLI args.

        ``bool`` fields emit their flag only when truthy; ``int`` fields emit
        ``--flag N`` when not ``None``; ``str`` fields emit ``--flag value``
        when non-empty. This keeps the command minimal — unset options simply
        aren't passed.
        """
        args: list[str] = []
        for field, flag, kind in YTDLP_FIELD_SPECS:
            val = yt_cfg.get(field)
            if kind == "bool":
                if val is True:
                    args.append(f"--{flag}")
            elif kind == "int":
                if val is not None:
                    args += [f"--{flag}", str(int(val))]
            else:  # "str"
                if val not in (None, ""):
                    args += [f"--{flag}", str(val)]
        return args

    async def _run_yt_dlp(
        self,
        url: str,
        *,
        playlist_start: int | None = None,
        playlist_end: int | None = None,
        dateafter: str | None = None,
        datebefore: str | None = None,
        extra_args: Mapping[str, Any] | None = None,
        structured: Mapping[str, Any] | None = None,
        download: Mapping[str, Any] | None = None,
        media_dir: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Run yt-dlp and return ``(parsed_entries, stderr_text)``.

        Raises :class:`TransientAdapterError` only on hard failures with no
        usable output; a query that simply yields zero entries returns empty
        lists so the caller can decide whether to fall back.

        ``playlist_start`` / ``playlist_end`` drive windowed pagination so a
        single sync can page past yt-dlp's default 50-item ceiling. ``dateafter``
        / ``datebefore`` are ``YYYYMMDD`` strings forwarded to yt-dlp's date
        filter. ``structured`` carries the remaining modelled ``yt_dlp`` fields
        (sorting, filtering, network throttling, …) translated by
        :meth:`_render_structured`. ``extra_args`` is a flat passthrough of any
        additional yt-dlp options operator-tuned via the workspace's centralised
        ``sync_settings`` policy (structured keys are skipped to avoid duplicate
        flags).

        When ``download`` enables any file-producing toggle and ``media_dir`` is
        provided, yt-dlp additionally writes those artifacts (thumbnail /
        subtitles / info-json / video) to ``media_dir`` via an ``%(id)s``
        output template; ``--skip-download`` is dropped only when the operator
        explicitly opts into ``download_video``.
        """
        cmd: list[str] = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-json",
            "--no-progress",
        ]
        download_enabled = self._any_download_enabled(download)
        if not (download_enabled and download.get("download_video")):
            # Default: scrape metadata only. Only drop this when the operator
            # explicitly wants the actual video file downloaded.
            cmd.append("--skip-download")
        if playlist_start is not None:
            cmd += ["--playlist-start", str(playlist_start)]
        if playlist_end is not None:
            cmd += ["--playlist-end", str(playlist_end)]
        if dateafter:
            cmd += ["--dateafter", dateafter]
        if datebefore:
            cmd += ["--datebefore", datebefore]
        # Structured fields (sorting / filtering / network / behaviour). The
        # global policy defaults keep --ignore-errors / --no-warnings enabled.
        # We always pin yt-dlp's built-in ``--retries`` (defaulting to
        # YTDLP_DEFAULT_RETRIES) so account-data and content-list calls share one
        # retry policy and an operator override (sync_settings.yt_dlp.retries)
        # wins when present. No bespoke retry loop wraps this call.
        effective_structured = dict(structured or {})
        if "retries" not in effective_structured:
            effective_structured["retries"] = YTDLP_DEFAULT_RETRIES
        cmd += self._render_structured(effective_structured)
        if download_enabled and media_dir:
            cmd += ["-o", os.path.join(media_dir, "%(id)s", "%(id)s.%(ext)s")]
            if download.get("write_thumbnail"):
                cmd.append("--write-thumbnail")
            if download.get("write_subtitles"):
                cmd.append("--write-sub")
            if download.get("write_auto_subtitles"):
                cmd.append("--write-auto-sub")
            sub_langs = download.get("subtitle_langs")
            if sub_langs and str(sub_langs).strip():
                cmd += ["--sub-langs", str(sub_langs).strip()]
            if download.get("write_info_json"):
                cmd.append("--write-info-json")
            if download.get("download_video") and download.get("video_format"):
                cmd += ["-f", str(download["video_format"]).strip()]
        if extra_args:
            for key, value in extra_args.items():
                if key in YTDLP_SPEC_KEYS:
                    # already emitted via structured rendering
                    continue
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
        self, url: str, *, playlist_end: int = 1, retries: int = YTDLP_DEFAULT_RETRIES
    ) -> tuple[dict[str, Any], str]:
        """Run yt-dlp with ``--dump-single-json`` and return the parsed object.

        The single playlist/JSON object carries the **channel-level** metadata
        (``channel_follower_count``, ``channel_id``, ``avatar``/``thumbnails``,
        ``playlist_count``) that the per-video line-delimited output omits, so
        account resolution and analytics can avoid the browser entirely. The
        ``entries`` array is ignored here (see :meth:`list_contents`).

        ``retries`` forwards yt-dlp's built-in ``--retries`` network policy
        (default :data:`YTDLP_DEFAULT_RETRIES`); we rely on yt-dlp's own internal
        retry rather than wrapping this call in a custom loop.
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
            "--retries",
            str(int(retries)),
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
            obj = json.loads(out.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise TransientAdapterError(f"yt-dlp returned invalid JSON: {exc}") from exc
        # yt-dlp can emit ``null`` (or a list/scalar) for profiles it cannot
        # resolve — e.g. Douyin accounts it does not support. Treat any non-dict
        # payload as "no profile" (empty dict) so the caller can decide whether
        # to fall back, instead of crashing on ``None.get(...)`` downstream.
        if not isinstance(obj, dict):
            return {}, err_text
        return obj, err_text

    @staticmethod
    async def extract_comments(url: str) -> list[dict[str, Any]]:
        """Best-effort comment extraction via yt-dlp.

        Uses yt-dlp's ``comments`` field (YouTube / TikTok / Douyin support it
        to varying degrees). Returns a normalized list of comment dicts; on any
        failure (unsupported site, network error, no comments) returns ``[]`` so
        callers never crash and the UI can show the required condition instead
        of a fabricated count.
        """
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--skip-download",
            "--no-warnings",
            "--no-progress",
            "--ignore-errors",
            "--retries",
            str(YTDLP_DEFAULT_RETRIES),
            "--print",
            "%(comments)j",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, _ = await asyncio.wait_for(
                proc.communicate(), timeout=YTDLP_TIMEOUT_SECONDS
            )
        except (TimeoutError, OSError):
            return []
        if not out:
            return []
        raw = out.decode("utf-8", "replace").strip()
        if not raw or raw == "null":
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        comments: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            replies = item.get("replies") or []
            comments.append(
                {
                    "platform_comment_id": str(item.get("id") or uuid4()),
                    "author_name": item.get("author")
                    or item.get("author_name")
                    or "未知用户",
                    "text": text,
                    "like_count": item.get("like_count"),
                    "reply_count": item.get("reply_count")
                    if item.get("reply_count") is not None
                    else (len(replies) if isinstance(replies, list) else None),
                    "published_at": (
                        datetime.fromtimestamp(item["timestamp"], tz=UTC)
                        if isinstance(item.get("timestamp"), (int, float))
                        else None
                    ),
                }
            )
        return comments

    def _resolve_retries(self, ctx: AdapterCallContext) -> int:
        """Resolve the yt-dlp ``--retries`` value from the call context.

        Honours an operator override at ``sync_settings.yt_dlp.retries`` and
        otherwise returns :data:`YTDLP_DEFAULT_RETRIES`. This is the single knob
        that tunes yt-dlp's built-in network retry across account-data calls.
        """
        yt_cfg = (ctx.config or {}) if isinstance(ctx.config, dict) else {}
        raw = (yt_cfg.get("yt_dlp") if isinstance(yt_cfg.get("yt_dlp"), dict) else {}).get(
            "retries"
        )
        if raw is None:
            return YTDLP_DEFAULT_RETRIES
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return YTDLP_DEFAULT_RETRIES
        return value if value >= 0 else YTDLP_DEFAULT_RETRIES

    async def _run_yt_dlp_single_cached(
        self, url: str, *, playlist_end: int = 1, retries: int = YTDLP_DEFAULT_RETRIES
    ) -> tuple[dict[str, Any], str]:
        """``_run_yt_dlp_single`` with a per-instance memo.

        ``resolve_account`` and ``fetch_account_analytics`` both query the same
        channel URL during one sync run; the memo collapses those into a single
        yt-dlp invocation, removing a redundant full subprocess per account. A
        cached failure (empty dict from a swallowed TransientAdapterError) is
        also reused — the identical command would fail again anyway, so retrying
        would only add latency. The cache is scoped to the adapter instance, so
        it never leaks across accounts or runs.
        """

        cached = self._single_json_cache.get(url)
        if cached is not None:
            return cached
        result = await self._run_yt_dlp_single(
            url, playlist_end=playlist_end, retries=retries
        )
        self._single_json_cache[url] = result
        return result

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

    @staticmethod
    def _clean_tags(raw: Any) -> list[str]:
        """Normalize yt-dlp ``tags`` into a clean list of short strings."""
        if not raw:
            return []
        out: list[str] = []
        for tag in raw:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if not tag or len(tag) > 64:
                continue
            if tag not in out:
                out.append(tag)
            if len(out) >= 30:
                break
        return out

    def _entry_to_content(
        self,
        entry: Mapping[str, Any],
        handle: str,
        ctx: AdapterCallContext,
        media: Mapping[str, Any] | None = None,
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
            media=media,
            tags=self._clean_tags(entry.get("tags")),
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
            data, _ = await self._run_yt_dlp_single_cached(
                self._account_url(handle),
                playlist_end=1,
                retries=self._resolve_retries(ctx),
            )
        except TransientAdapterError:
            data = {}
        display = data.get("uploader") or data.get("channel")
        if not display:
            logger.info(
                "yt_dlp account extraction failed for %s/%s; using browser fallback",
                self.platform,
                handle,
            )
            return await self._browser_resolve(ctx, locator)

        # yt-dlp returned a usable profile. It often omits the avatar / bio, so
        # when those are missing we re-query the browser adapter purely to fill
        # them in — keeping the more precise yt-dlp display name and channel id.
        avatar = self._extract_thumbnail(data)
        description = data.get("description")
        channel_id = data.get("channel_id") or data.get("uploader_id")
        language = (
            "en"
            if self.platform == "youtube"
            else ("zh" if self.platform == "douyin" else None)
        )
        result = PlatformAccountData(
            external_id=handle,
            username=handle,
            display_name=display,
            profile_url=self._account_url(handle),
            avatar_url=avatar,
            description=description,
            country=None,
            language=language,
            is_verified=None,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={"method": "yt_dlp", "channel_id": channel_id},
        )
        # yt-dlp is the primary, self-sufficient source. We deliberately do NOT
        # trigger a browser fallback just because the avatar/description are
        # missing — those are optional fields yt-dlp may legitimately omit, and
        # the browser path is reserved for hard failures (no display name above,
        # or a transient yt-dlp error in list_contents). Browser is only started
        # when yt-dlp is unavailable, never to "fill gaps".
        return result

    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        handle = self._normalize_handle(external_id)
        try:
            data, _ = await self._run_yt_dlp_single_cached(
                self._account_url(handle),
                playlist_end=1,
                retries=self._resolve_retries(ctx),
            )
        except TransientAdapterError:
            data = {}
        # ``analytics_fetched`` tells the sync engine whether yt-dlp actually
        # returned an account object. TikTok/Douyin user pages frequently omit
        # follower / video / view counts through yt-dlp, yet the fetch still
        # succeeds (the profile and the content list are fully extractable). That
        # is a *platform limitation*, not a failed extraction, so it must NOT be
        # reported as a degraded sync — the missing fields are surfaced via
        # ``unavailable_metrics``. Only a genuinely empty result (a transient
        # yt-dlp failure swallowed above) should be treated as degraded.
        analytics_fetched = bool(data)
        follower = data.get("channel_follower_count") or data.get("subscriber_count")
        playlist_count = data.get("playlist_count")
        channel_view_count = data.get("view_count")
        metrics: dict[str, int | float | None] = {
            "follower_count": int(follower) if follower is not None else None,
            "video_count": int(playlist_count) if playlist_count is not None else None,
            # YouTube channel JSON exposes lifetime views, so we can report a
            # real account-level total plays. TikTok/Douyin profiles do not
            # expose total views publicly, so it stays None here and is derived
            # from synced content views in the sync executor instead.
            "total_view_count": (
                int(channel_view_count) if channel_view_count is not None else None
            )
            if self.platform == "youtube"
            else None,
        }
        analytics_source = "yt_dlp"
        # TikTok / Douyin profiles do not expose account-level metrics through
        # yt-dlp's channel JSON (only the video list does — ``resolve_account``
        # already delegates the *profile* to the browser adapter for these
        # platforms because the channel JSON omits the uploader). The browser
        # adapter, however, can scrape the public profile stats (follower / like
        # / video counts) from the rendered page. So whenever yt-dlp yields no
        # usable account metrics for these platforms, delegate analytics to the
        # browser adapter too, instead of leaving the counts permanently
        # unavailable. This covers both TikTok (yt-dlp fetches the channel but
        # no metrics) and Douyin (yt-dlp returns nothing usable at all). The
        # browser path is best-effort: if it also fails, the metrics stay None
        # and are surfaced via ``unavailable_metrics`` rather than misreported
        # as a degraded sync. YouTube keeps using yt-dlp's channel JSON, which
        # does carry these metrics.
        if self.platform in ("tiktok", "douyin") and all(
            v is None for v in metrics.values()
        ):
            try:
                fb = await self._browser_analytics(ctx, handle)
                merged: dict[str, int | float | None] = dict(metrics)
                for key, val in fb.metrics.items():
                    if merged.get(key) is None and val is not None:
                        merged[key] = int(val) if isinstance(val, (int, float)) else val
                metrics = merged
                analytics_source = "browser"
                if any(v is not None for v in fb.metrics.values()):
                    # We obtained real analytics from the browser, so this is a
                    # successful (partial) extraction, not a degraded sync.
                    analytics_fetched = True
            except Exception as exc:  # noqa: BLE001 - browser is best-effort here
                logger.warning(
                    "browser analytics fallback failed for %s/%s: %s",
                    self.platform,
                    handle,
                    exc,
                )

        unavailable = tuple(k for k, v in metrics.items() if v is None)
        return PlatformMetricsData(
            external_id=handle,
            captured_at=ctx.observed_at,
            metrics=metrics,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            unavailable_metrics=unavailable,
            metadata={
                "method": "yt_dlp",
                "analytics_fetched": analytics_fetched,
                "analytics_source": analytics_source,
            },
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
        # Download policy (yt-dlp file-producing flags). When enabled we stage
        # artifacts under a per-account media dir resolved from the workspace
        # media root; the sync executor stores the produced paths on the row.
        download_cfg = cfg.get("download") if isinstance(cfg.get("download"), dict) else None
        media_root = cfg.get("media_root") if isinstance(cfg.get("media_root"), str) else None
        media_dir = None
        if download_cfg and media_root and self._any_download_enabled(download_cfg):
            media_dir = os.path.join(media_root, self._safe_dir(handle))
            os.makedirs(media_dir, exist_ok=True)
        if published_after is not None and not dateafter:
            dateafter = published_after.strftime("%Y%m%d")

        offset = int(cursor) if cursor and str(cursor).isdigit() else 0
        window = page_size
        if max_items is not None:
            window = min(window, max(1, int(max_items) - offset))
            if window <= 0:
                return AdapterPage(items=(), next_cursor=None)

        # Default windowed pagination; on the first page honour an optional
        # per-account ``playlist_start`` (skip the first N works of the catalogue).
        if offset == 0 and yt_cfg.get("playlist_start"):
            playlist_start = int(yt_cfg["playlist_start"])
        else:
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
                structured=yt_cfg if isinstance(yt_cfg, dict) else None,
                download=download_cfg,
                media_dir=media_dir,
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
            media = None
            vid = entry.get("id")
            if media_dir and media_root and vid:
                # ``media_root`` is workspace-scoped (MEDIA_ROOT/<ws>); the
                # relative ``base`` stored on the row must be relative to the
                # global MEDIA_ROOT so the ``/media`` route resolves it.
                media = self._collect_media(
                    os.path.dirname(media_root), media_dir, str(vid)
                )
            content = self._entry_to_content(entry, handle, ctx, media=media)
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
        # A partial window (fetched < window) is treated as the genuine end of
        # the catalogue — NOT a signal to switch to the browser adapter. yt-dlp
        # is the primary acquisition path; browser is only used on a hard
        # failure (TransientAdapterError or an empty first page above).
        return AdapterPage(items=tuple(items), next_cursor=next_cursor)

    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData:
        if self.platform == "youtube":
            url = f"https://www.youtube.com/watch?v={external_id}"
            try:
                entries, _ = await self._run_yt_dlp(
                    url, structured={"ignore_errors": True, "no_warnings": True}
                )
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
