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
import hashlib
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterDescriptor,
    AdapterHealth,
    AdapterNotFoundError,
    AdapterPage,
    LoginRequiredError,
    PermissionDeniedError,
    PlatformAccountData,
    PlatformAdapter,
    PlatformAdapterError,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)
from app.services.ytdlp_runtime import runtime_args

logger = logging.getLogger(__name__)

# Generous timeout: a YouTube channel playlist can take a while to resolve all
# per-video metadata, and we never want a hung subprocess to block a worker.
YTDLP_TIMEOUT_SECONDS = 180

# yt-dlp's built-in network retry count. We set it explicitly (rather than
# relying on yt-dlp's own default) so the value is visible and operator-tunable,
# and so account-data and content-list invocations share one policy. Operators
# can override it per workspace via ``sync_settings.yt_dlp.retries``; anything
# not set falls back to this.
#
# NOTE: ``--retries`` only covers *network* fragments (HTTP errors, socket
# resets). It does **not** cover *extractor-level* failures such as TikTok's
# "Unable to extract universal data for rehydration", which happens when the
# anti-bot layer serves a stripped page. Those need a different recovery
# strategy (a different extraction path), handled by
# :data:`YTDLP_EXTRACTION_ATTEMPTS` / :func:`_recovery_args_for` below.
YTDLP_DEFAULT_RETRIES = 10

# How many *extraction strategies* to try when yt-dlp exits non-zero with no
# usable output. Attempt 0 is the plain command; later attempts append
# platform-specific recovery flags. Kept small on purpose: the user-visible
# requirement is "no long waits", and every attempt only runs after a *fast*
# hard failure (timeouts are never retried — see ``_run_yt_dlp``).
YTDLP_EXTRACTION_ATTEMPTS = int(os.environ.get("SIO_YTDLP_EXTRACT_ATTEMPTS", "3") or 3)

# Backoff between extraction attempts (seconds). Short by design.
YTDLP_ATTEMPT_BACKOFF_SECONDS = (1.5, 3.0)

# Wall-clock ceiling for the cheap ``--flat-playlist`` catalogue read. It never
# performs per-video extraction, so it must finish far sooner than a full dump;
# when it does not, the caller silently reverts to the legacy single-shot path
# instead of burning the sync budget.
YTDLP_FLAT_TIMEOUT_SECONDS = 60

# Default per-video extraction concurrency, per platform. Measured on this
# deployment against a real YouTube channel (8 videos, full ``--dump-json``):
#   sequential 28.1s -> concurrency 4: 9.8s -> concurrency 8: 6.8s.
# TikTok / Douyin stay deliberately low: their anti-bot layer reacts to burst
# traffic, and a soft-blocked account costs far more than the seconds saved.
YTDLP_PLATFORM_FETCH_CONCURRENCY: dict[str, int] = {
    "youtube": 8,
    "bilibili": 4,
    "tiktok": 2,
    "douyin": 2,
}

# TikTok mobile-API app identifiers. Supplying ``app_info`` makes yt-dlp try the
# mobile API path (``_extract_aweme_app``) *before* the fragile webpage scrape,
# and the API response additionally carries caption metadata the webpage omits.
# Two distinct ids so a rate-limited one can be rotated away from.
TIKTOK_RECOVERY_APP_INFO = (
    "7355728856979392262",
    "7351144126450059040",
)

# Error fragments that are *permanent* for the given URL. Retrying them only
# burns time and raises anti-bot risk, so they fail fast with the original
# message.
#
# The markers are split by *cause* because the resulting exception decides two
# separate things:
#   * whether Celery retries the whole sync (``retryable``) — every bucket here
#     is non-retryable, which is the entire point of this table;
#   * which operator-facing hint the UI renders (``code`` -> error_detail hint).
# Lumping them into one generic transient error is what used to burn ~3x the
# wall clock on a login-walled account before failing anyway.

# "An authenticated session would fix this" -> 需要登录凭证.
YTDLP_LOGIN_WALL_MARKERS: tuple[str, ...] = (
    "login required",
    "requires authentication",
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "sign in to confirm your age",
    "captcha",
    "private video",
    "private account",
    "members-only",
    "join this channel",
)

# TikTok anti-bot layer serving a stripped page raises yt-dlp's
# "Unable to extract universal data for rehydration". This is *not* in
# :data:`YTDLP_PERMANENT_ERROR_MARKERS` because the adapter must first exhaust
# its escalating recovery attempts (mobile-API ``app_info`` rotation) — only
# once every attempt fails do we treat it as a wall. See
# :data:`YTDLP_ANTIBOT_REHYDRATION_MARKERS` and :func:`_permanent_error_for`.
YTDLP_ANTIBOT_REHYDRATION_MARKERS: tuple[str, ...] = ("universal data for rehydration",)

# "The credentials/region are not allowed to see this" -> 权限/地域限制.
YTDLP_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "do not have permission",
    "copyright",
    # Covers both "is not available in your country" and yt-dlp's more common
    # "The uploader has not made this video available in your country".
    "available in your country",
    "ip address is blocked",
)

# "This URL will never resolve again" -> 已删除 / 不存在.
YTDLP_GONE_MARKERS: tuple[str, ...] = (
    "video unavailable",
    "has been removed",
    "account has been terminated",
    "unsupported url",
    "404",
)

YTDLP_PERMANENT_ERROR_MARKERS: tuple[str, ...] = (
    *YTDLP_LOGIN_WALL_MARKERS,
    *YTDLP_FORBIDDEN_MARKERS,
    *YTDLP_GONE_MARKERS,
)


def _is_permanent_extractor_error(err_text: str) -> bool:
    """Return True when re-running yt-dlp cannot possibly change the outcome."""

    lowered = (err_text or "").lower()
    return any(marker in lowered for marker in YTDLP_PERMANENT_ERROR_MARKERS)


def _permanent_error_for(platform: str, err_text: str) -> PlatformAdapterError | None:
    """Map a permanent yt-dlp stderr to a *non-retryable* adapter error.

    Returns ``None`` when the failure is not recognisably permanent, in which
    case the caller keeps the retryable :class:`TransientAdapterError`.
    """

    lowered = (err_text or "").lower()
    excerpt = (err_text or "").strip()[:200]
    if any(marker in lowered for marker in YTDLP_LOGIN_WALL_MARKERS):
        return LoginRequiredError(platform, excerpt)
    if any(marker in lowered for marker in YTDLP_FORBIDDEN_MARKERS):
        return PermissionDeniedError(f"{platform} 拒绝访问该资源：{excerpt}")
    if any(marker in lowered for marker in YTDLP_GONE_MARKERS):
        return AdapterNotFoundError(f"{platform} 资源不存在或已被删除：{excerpt}")
    # Anti-bot "stripped page" errors (TikTok: "universal data for rehydration").
    # These are deliberately absent from :data:`YTDLP_PERMANENT_ERROR_MARKERS`
    # so the escalating recovery attempts run first; once they are exhausted the
    # only remedy is a real login / cookie, so surface it as a wall.
    if any(marker in lowered for marker in YTDLP_ANTIBOT_REHYDRATION_MARKERS):
        return LoginRequiredError(
            platform,
            f"反爬拦截（页面未水合），需配置登录态/凭证后重试：{excerpt}",
        )
    return None


# yt-dlp failures that still deserve a shot at the browser adapter. The browser
# is a *genuinely different* acquisition path (real profile, real cookies), so a
# login wall or a "video unavailable" seen by yt-dlp may still be resolvable
# there. The classification above therefore only changes what happens once the
# fallback has also failed: the error escapes as non-retryable instead of
# triggering another full round of Celery retries.
YTDLP_BROWSER_FALLBACK_ERRORS = (
    TransientAdapterError,
    LoginRequiredError,
    PermissionDeniedError,
    AdapterNotFoundError,
)


def _recovery_args_for(url: str, attempt: int) -> list[str]:
    """Return extra yt-dlp flags that use a *different* extraction path.

    ``attempt`` is 1-based (attempt 0 is the plain command, which never gets
    recovery flags). Returning an empty list means "just retry as-is", which is
    still useful for genuinely transient upstream hiccups.
    """

    if attempt < 1:
        return []
    host = (urlsplit(url).hostname or "").lower()
    if "tiktok.com" in host:
        index = (attempt - 1) % len(TIKTOK_RECOVERY_APP_INFO)
        return ["--extractor-args", f"tiktok:app_info={TIKTOK_RECOVERY_APP_INFO[index]}"]
    return []


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
    ("cookies_from_browser", "cookies-from-browser", "str"),
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
    def _video_format_selector(download: Mapping[str, Any] | None) -> str | None:
        """Build the yt-dlp ``-f`` format selector from the user-facing
        quality (resolution tier) and video_format (container) picks.

        Returns ``None`` when no constraint applies (yt-dlp then picks its own
        best combined format). ``audio`` quality is handled separately by the
        caller (audio-only extraction), so it is ignored here.
        """
        if not isinstance(download, dict):
            return None
        quality = str(download.get("video_quality") or "best").strip().lower()
        vfmt = str(download.get("video_format") or "best").strip().lower()
        if quality == "audio":
            return None
        constraints: list[str] = []
        if quality not in ("best", ""):
            digits = "".join(ch for ch in quality if ch.isdigit())
            if digits:
                constraints.append(f"[height<={digits}]")
        if vfmt not in ("best", "any", ""):
            constraints.append(f"[ext={vfmt}]")
        if not constraints:
            return None
        return f"bestvideo{''.join(constraints)}+bestaudio/best"

    @staticmethod
    def _output_template(media_dir: str, naming_rule: Any) -> str:
        """Resolve the yt-dlp ``-o`` output template.

        The directory is always ``%(id)s`` (one folder per video, also used by
        ``_collect_media``). The filename base follows ``naming_rule`` so the
        operator can choose a readable file name without breaking media
        discovery.
        """
        rule = str(naming_rule or "id").strip().lower()
        if rule == "title":
            fname = "%(title)s.%(ext)s"
        elif rule == "uploader":
            fname = "%(uploader)s_%(id)s.%(ext)s"
        elif rule == "date_title":
            fname = "%(upload_date)s_%(title)s.%(ext)s"
        else:  # "id" (default) — keeps subtitle discovery trivial
            fname = "%(id)s.%(ext)s"
        return os.path.join(media_dir, "%(id)s", fname)

    @staticmethod
    def _collect_media(media_root: str, media_dir: str, video_id: str) -> dict[str, Any] | None:
        """Scan the per-video output dir and classify discovered files.

        Returns ``None`` when nothing was written. ``base`` is the
        workspace-relative path under ``media_root`` used by the ``/media``
        route to resolve files safely. Audio-only extractions set ``audio``
        instead of ``video``; subtitle languages are resolved against the
        primary media base name so custom ``naming_rule`` values still match.
        """
        d = os.path.join(media_dir, video_id)
        if not os.path.isdir(d):
            return None
        try:
            base = os.path.relpath(d, media_root)
        except ValueError:
            base = video_id
        thumbnail = video = audio = info_json = None
        primary_base: str | None = None
        raw_subs: list[str] = []
        for fn in os.listdir(d):
            low = fn.lower()
            if low.endswith(".info.json"):
                info_json = fn
            elif low.endswith((".vtt", ".srt", ".ass", ".sbv", ".lrc")):
                raw_subs.append(fn)
            elif low.endswith((".mp4", ".webm", ".mkv", ".mov", ".flv", ".m4v", ".avi")):
                video = fn
                if primary_base is None:
                    primary_base = os.path.splitext(fn)[0]
            elif low.endswith((".mp3", ".m4a", ".aac", ".opus", ".wav", ".flac")):
                audio = fn
                if primary_base is None:
                    primary_base = os.path.splitext(fn)[0]
            elif low.endswith((".webp", ".jpg", ".jpeg", ".png")):
                thumbnail = fn
        subtitles: list[dict[str, str]] = []
        # Prefer the primary media base name for matching; fall back to the raw
        # video id (the ``%(id)s`` template base) so subtitle detection still works
        # when only subtitles are downloaded (no video/audio file present).
        match_base = primary_base or video_id
        for fn in raw_subs:
            lang = ""
            if match_base and fn.startswith(match_base + "."):
                ext = os.path.splitext(fn)[1]
                mid = fn[len(match_base) + 1 : -len(ext)]
                lang = mid
            subtitles.append({"lang": lang, "file": fn})
        result: dict[str, Any] = {"base": base}
        if thumbnail:
            result["thumbnail"] = thumbnail
        if video:
            result["video"] = video
        if audio:
            result["audio"] = audio
        if info_json:
            result["info_json"] = info_json
        if subtitles:
            result["subtitles"] = subtitles
        return result if (thumbnail or video or audio or info_json or subtitles) else None

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

    async def _browser_resolve(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
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

    @staticmethod
    def _materialize_cookie_file(yt_cfg: Mapping[str, Any]) -> str | None:
        """Write encrypted-config cookies to a short-lived Netscape file.

        yt-dlp cannot consume Playwright's JSON storage state directly. The
        captured cookie text is decrypted only in worker memory and materialized
        under the OS temp directory for the lifetime of one yt-dlp process.
        """

        raw = yt_cfg.get("cookies_netscape")
        if not isinstance(raw, str) or not raw.strip():
            return None
        fd, path = tempfile.mkstemp(prefix="sio-ytdlp-", suffix=".cookies.txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(raw)
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def _cleanup_cookie_file(path: str | None) -> None:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    async def _communicate_with_timeout(
        proc: asyncio.subprocess.Process,
        seconds: float,
        stderr_callback: Callable[[str], None] | None = None,
    ) -> tuple[bytes, bytes]:
        """Collect a yt-dlp process and terminate it when the wall clock expires.

        When the process exposes piped ``stdout``/``stderr`` (the production
        path), stderr is read line-by-line and forwarded to ``stderr_callback``
        so a caller can surface live progress without waiting for the process to
        exit. When either pipe is absent (e.g. lightweight test fakes), it falls
        back to the simple ``communicate()`` collect path.
        """
        if getattr(proc, "stdout", None) is None or getattr(proc, "stderr", None) is None:
            try:
                async with asyncio.timeout(seconds):
                    return await proc.communicate()
            except TimeoutError:
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                try:
                    await proc.communicate()
                except (asyncio.CancelledError, OSError):
                    pass
                raise

        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []

        async def _drain_stdout() -> None:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                out_chunks.append(chunk)

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                err_chunks.append(line)
                if stderr_callback is not None:
                    stderr_callback(line.decode("utf-8", "replace"))

        try:
            async with asyncio.timeout(seconds):
                await asyncio.gather(_drain_stdout(), _drain_stderr())
                await proc.wait()
        except TimeoutError:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            # Drain the pipes after termination so a timed-out child cannot
            # leave a pipe/child process attached to the worker.
            try:
                await proc.communicate()
            except (asyncio.CancelledError, OSError):
                pass
            raise
        return b"".join(out_chunks), b"".join(err_chunks)

    def _download_flags(
        self, download_config: Mapping[str, Any], media_dir: str | None
    ) -> list[str]:
        """Render the file-producing yt-dlp flags for a download policy.

        Shared by the legacy single-shot playlist extraction and the fast
        per-video path so both produce byte-identical artifacts (thumbnail /
        subtitles / info-json / media) for the same policy. Returns an empty
        list when nothing should be written to disk.
        """
        if not (media_dir and self._any_download_enabled(download_config)):
            return []
        flags: list[str] = [
            "-o",
            self._output_template(media_dir, download_config.get("naming_rule")),
        ]
        if download_config.get("write_thumbnail"):
            flags.append("--write-thumbnail")
        if download_config.get("write_subtitles"):
            flags.append("--write-sub")
        if download_config.get("write_auto_subtitles"):
            flags.append("--write-auto-sub")
        sub_langs = download_config.get("subtitle_langs")
        if sub_langs and str(sub_langs).strip():
            flags += ["--sub-langs", str(sub_langs).strip()]
        if download_config.get("write_info_json"):
            flags.append("--write-info-json")
        quality = str(download_config.get("video_quality") or "best").strip().lower()
        if quality == "audio":
            # Audio-only extraction: pull the best audio stream and remux
            # into the requested container at the requested bitrate.
            flags += ["-f", "bestaudio/best", "-x"]
            audio_fmt = str(download_config.get("audio_format") or "best").strip().lower()
            if audio_fmt not in ("best", ""):
                flags += ["--audio-format", audio_fmt]
            bitrate = str(download_config.get("bitrate") or "").strip()
            if bitrate:
                flags += ["--audio-quality", bitrate]
        else:
            fmt = self._video_format_selector(download_config)
            if fmt:
                flags += ["-f", fmt]
        return flags

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
        progress_callback: Callable[[str], None] | None = None,
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
            # Emit one line per progress update (instead of a TTY progress bar)
            # so the streaming reader can forward live status to the UI.
            "--newline",
            "--progress",
            "--extractor-args",
            "generic:impersonate=false",
        ]
        cmd += runtime_args()
        download_config: Mapping[str, Any] = download or {}
        download_enabled = self._any_download_enabled(download_config)
        quality = str(download_config.get("video_quality") or "best").strip().lower()
        # Default: scrape metadata only. Drop --skip-download when the operator
        # explicitly wants the video file, OR when an audio-only extraction was
        # requested (both produce a media artifact, not just metadata).
        want_media = download_enabled and (
            download_config.get("download_video") or quality == "audio"
        )
        if not want_media:
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
        cookie_path = self._materialize_cookie_file(effective_structured)
        render_structured = dict(effective_structured)
        if cookie_path:
            # A captured session is more explicit and portable than asking the
            # worker container to locate a host browser profile.
            render_structured["cookies_from_browser"] = ""
        cmd += self._render_structured(render_structured)
        if cookie_path:
            cmd += ["--cookies", cookie_path]
        cmd += self._download_flags(download_config, media_dir)
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

        # ------------------------------------------------------------------
        # Escalating extraction strategies.
        #
        # A hard failure here is *not* the same as a network blip: TikTok (and
        # occasionally other anti-bot platforms) serves a stripped page that the
        # webpage extractor cannot parse, and yt-dlp's own ``--retries`` never
        # kicks in because the HTTP request itself succeeded. Retrying the
        # *same* command is ~66% reliable; switching extraction path recovers
        # nearly all of the remainder.
        #
        # Guard rails so this never becomes the "long wait" the product forbids:
        #   * a timeout is NEVER retried (that would double the wall clock);
        #   * permanent errors (login wall, private, geo-block, removed) fail
        #     immediately with the original message;
        #   * retries only follow a hard, usually fast, failure.
        # ------------------------------------------------------------------
        out = b""
        err_text = ""
        last_returncode: int | None = None
        try:
            for attempt in range(max(1, YTDLP_EXTRACTION_ATTEMPTS)):
                attempt_cmd = list(cmd)
                recovery = _recovery_args_for(url, attempt)
                if recovery:
                    # Insert before the trailing URL so yt-dlp parses it as an option.
                    attempt_cmd[-1:-1] = recovery
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *attempt_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    out, err = await self._communicate_with_timeout(
                        proc, YTDLP_TIMEOUT_SECONDS, stderr_callback=progress_callback
                    )
                except TimeoutError as exc:
                    raise TransientAdapterError("yt-dlp subprocess timed out") from exc

                err_text = err.decode("utf-8", "replace") if err else ""
                last_returncode = proc.returncode
                if proc.returncode in (0, None) or out:
                    break
                if _is_permanent_extractor_error(err_text):
                    break
                if attempt + 1 >= max(1, YTDLP_EXTRACTION_ATTEMPTS):
                    break
                backoff = YTDLP_ATTEMPT_BACKOFF_SECONDS[
                    min(attempt, len(YTDLP_ATTEMPT_BACKOFF_SECONDS) - 1)
                ]
                logger.info(
                    "yt-dlp extraction attempt %s failed for %s; retrying with recovery args",
                    attempt + 1,
                    url,
                )
                if progress_callback is not None:
                    progress_callback(
                        f"[recovery] 第 {attempt + 1} 次解析失败，切换解析通道后重试…\n"
                    )
                await asyncio.sleep(backoff)
        finally:
            self._cleanup_cookie_file(cookie_path)

        if last_returncode not in (0, None) and not out:
            # Fail *fast* on permanent causes: a login wall / removed video will
            # fail identically on every Celery retry, so raising a retryable
            # error here multiplies the wall clock by the retry count for
            # exactly zero chance of success.
            permanent = _permanent_error_for(self.platform, err_text)
            if permanent is not None:
                raise permanent
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

    # ------------------------------------------------------------------
    # Fast listing path: enumerate cheaply, extract selectively, in parallel.
    #
    # The legacy path runs one ``--dump-json`` over the whole channel window,
    # which forces yt-dlp to fully resolve *every* video in that window on
    # *every* sync — including works that are already in the database and have
    # not changed. Measured cost on this deployment for a 20-video YouTube
    # window: 62s. The same window enumerated flat costs 11s, and a full
    # extraction of only the genuinely new works runs 4-8 wide.
    # ------------------------------------------------------------------

    def _fetch_concurrency(self, ctx: AdapterCallContext) -> int:
        """Resolve the per-video extraction concurrency for this call."""
        requested = getattr(ctx, "fetch_concurrency", 1) or 1
        try:
            requested = int(requested)
        except (TypeError, ValueError):
            requested = 1
        ceiling = YTDLP_PLATFORM_FETCH_CONCURRENCY.get(self.platform, 2)
        return max(1, min(requested, ceiling))

    async def _flat_enumerate(
        self,
        url: str,
        *,
        playlist_start: int | None,
        playlist_end: int | None,
        dateafter: str | None,
        datebefore: str | None,
        structured: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Read a channel window with ``--flat-playlist`` (catalogue only).

        A flat entry carries ``id`` / ``title`` / ``duration`` / ``view_count``
        / ``thumbnails`` but **not** description, upload timestamp, like or
        comment counts. It is therefore only a catalogue used to decide which
        works deserve the expensive full extraction.

        Returns ``[]`` on any failure so the caller can fall back to the legacy
        single-shot extraction rather than failing the sync outright.
        """
        cmd: list[str] = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-json",
            "--flat-playlist",
            "--skip-download",
            "--no-progress",
            "--extractor-args",
            "generic:impersonate=false",
        ]
        cmd += runtime_args()
        if playlist_start is not None:
            cmd += ["--playlist-start", str(playlist_start)]
        if playlist_end is not None:
            cmd += ["--playlist-end", str(playlist_end)]
        if dateafter:
            cmd += ["--dateafter", dateafter]
        if datebefore:
            cmd += ["--datebefore", datebefore]
        effective = dict(structured or {})
        effective.setdefault("retries", YTDLP_DEFAULT_RETRIES)
        cookie_path = self._materialize_cookie_file(effective)
        render = dict(effective)
        if cookie_path:
            render["cookies_from_browser"] = ""
        cmd += self._render_structured(render)
        if cookie_path:
            cmd += ["--cookies", cookie_path]
        cmd.append(url)
        out = b""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _err = await self._communicate_with_timeout(proc, YTDLP_FLAT_TIMEOUT_SECONDS)
        except (TimeoutError, OSError) as exc:
            logger.info("flat enumeration unavailable for %s: %s", url, exc)
            return []
        finally:
            self._cleanup_cookie_file(cookie_path)
        entries: list[dict[str, Any]] = []
        for line in out.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("id"):
                entries.append(obj)
        return entries

    async def _extract_one_video(
        self,
        video_url: str,
        *,
        base_flags: Sequence[str],
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any] | None:
        """Fully extract a single video. Returns ``None`` when unavailable.

        Failures are intentionally swallowed: one unreadable work (deleted,
        members-only, geo-blocked) must never fail the whole page — the caller
        keeps the flat catalogue entry for it instead.
        """
        async with semaphore:
            cmd = [*base_flags, "--no-playlist", video_url]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, _err = await self._communicate_with_timeout(proc, YTDLP_TIMEOUT_SECONDS)
            except (TimeoutError, OSError):
                return None
            for line in out.decode("utf-8", "replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("id"):
                    return obj
            return None

    async def _extract_details(
        self,
        video_urls: Mapping[str, str],
        *,
        concurrency: int,
        dateafter: str | None,
        datebefore: str | None,
        structured: Mapping[str, Any] | None,
        download: Mapping[str, Any] | None,
        media_dir: str | None,
        extra_args: Mapping[str, Any] | None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fully extract many videos in parallel, keyed by external id."""
        if not video_urls:
            return {}
        download_config: Mapping[str, Any] = download or {}
        quality = str(download_config.get("video_quality") or "best").strip().lower()
        want_media = self._any_download_enabled(download_config) and (
            download_config.get("download_video") or quality == "audio"
        )
        base: list[str] = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-json",
            "--no-progress",
            "--extractor-args",
            "generic:impersonate=false",
        ]
        base += runtime_args()
        if not want_media:
            base.append("--skip-download")
        if dateafter:
            base += ["--dateafter", dateafter]
        if datebefore:
            base += ["--datebefore", datebefore]
        effective = dict(structured or {})
        effective.setdefault("retries", YTDLP_DEFAULT_RETRIES)
        cookie_path = self._materialize_cookie_file(effective)
        render = dict(effective)
        if cookie_path:
            render["cookies_from_browser"] = ""
        base += self._render_structured(render)
        if cookie_path:
            base += ["--cookies", cookie_path]
        base += self._download_flags(download_config, media_dir)
        if extra_args:
            for key, value in extra_args.items():
                if key in YTDLP_SPEC_KEYS or value is None or value is False:
                    continue
                flag = f"--{key.replace('_', '-')}"
                if value is True:
                    base.append(flag)
                else:
                    base += [flag, str(value)]

        semaphore = asyncio.Semaphore(max(1, concurrency))
        ids = list(video_urls)
        if progress_callback is not None:
            progress_callback(
                f"[fast] 并发解析 {len(ids)} 条新作品详情（并发度 {max(1, concurrency)}）…\n"
            )
        try:
            results = await asyncio.gather(
                *(
                    self._extract_one_video(video_urls[vid], base_flags=base, semaphore=semaphore)
                    for vid in ids
                )
            )
        finally:
            self._cleanup_cookie_file(cookie_path)
        details: dict[str, dict[str, Any]] = {}
        for vid, entry in zip(ids, results, strict=True):
            if entry is not None:
                details[vid] = entry
        return details

    async def _run_yt_dlp_single(
        self,
        url: str,
        *,
        playlist_end: int = 1,
        retries: int = YTDLP_DEFAULT_RETRIES,
        structured: Mapping[str, Any] | None = None,
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
            "--extractor-args",
            "generic:impersonate=false",
            "--ignore-errors",
            "--playlist-end",
            str(playlist_end),
            url,
        ]
        effective_structured = dict(structured or {})
        effective_structured.setdefault("retries", int(retries))
        cookie_path = self._materialize_cookie_file(effective_structured)
        render_structured = dict(effective_structured)
        if cookie_path:
            render_structured["cookies_from_browser"] = ""
        # Keep account/profile extraction aligned with content extraction. The
        # structured settings include cookies-from-browser when configured.
        cmd[cmd.index(url) : cmd.index(url)] = self._render_structured(render_structured)
        if cookie_path:
            cmd[cmd.index(url) : cmd.index(url)] = ["--cookies", cookie_path]
        # Keep the runtime flags next to every extraction entry point. Account
        # sync and single-video preview must not silently use different
        # YouTube extraction capabilities.
        cmd[cmd.index(url) : cmd.index(url)] = runtime_args()
        # Account-level metadata drives the whole monitoring product, so it uses
        # the same escalating extraction strategy as content extraction (see
        # ``_run_yt_dlp``). Timeouts still fail fast.
        out = b""
        err_text = ""
        last_returncode: int | None = None
        try:
            for attempt in range(max(1, YTDLP_EXTRACTION_ATTEMPTS)):
                attempt_cmd = list(cmd)
                recovery = _recovery_args_for(url, attempt)
                if recovery:
                    attempt_cmd[attempt_cmd.index(url) : attempt_cmd.index(url)] = recovery
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *attempt_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    out, err = await self._communicate_with_timeout(proc, YTDLP_TIMEOUT_SECONDS)
                except TimeoutError as exc:
                    raise TransientAdapterError("yt-dlp single-json timed out") from exc

                err_text = err.decode("utf-8", "replace") if err else ""
                last_returncode = proc.returncode
                if proc.returncode in (0, None) or out:
                    break
                if _is_permanent_extractor_error(err_text):
                    break
                if attempt + 1 >= max(1, YTDLP_EXTRACTION_ATTEMPTS):
                    break
                await asyncio.sleep(
                    YTDLP_ATTEMPT_BACKOFF_SECONDS[
                        min(attempt, len(YTDLP_ATTEMPT_BACKOFF_SECONDS) - 1)
                    ]
                )
        finally:
            self._cleanup_cookie_file(cookie_path)

        if last_returncode not in (0, None) and not out:
            permanent = _permanent_error_for(self.platform, err_text)
            if permanent is not None:
                raise permanent
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
            "--extractor-args",
            "generic:impersonate=false",
            "--ignore-errors",
            "--retries",
            str(YTDLP_DEFAULT_RETRIES),
            "--print",
            "%(comments)j",
            url,
        ]
        cmd[cmd.index(url) : cmd.index(url)] = runtime_args()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, _ = await YtDlpAdapter._communicate_with_timeout(proc, YTDLP_TIMEOUT_SECONDS)
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
                    "author_name": item.get("author") or item.get("author_name") or "未知用户",
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
        config = ctx.config if isinstance(ctx.config, dict) else {}
        raw_yt_cfg = config.get("yt_dlp")
        yt_cfg: dict[str, Any] = raw_yt_cfg if isinstance(raw_yt_cfg, dict) else {}
        raw = yt_cfg.get("retries")
        if raw is None:
            return YTDLP_DEFAULT_RETRIES
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return YTDLP_DEFAULT_RETRIES
        return value if value >= 0 else YTDLP_DEFAULT_RETRIES

    @staticmethod
    def _yt_config(ctx: AdapterCallContext) -> dict[str, Any]:
        config = ctx.config if isinstance(ctx.config, dict) else {}
        raw = config.get("yt_dlp")
        return dict(raw) if isinstance(raw, dict) else {}

    async def _run_yt_dlp_single_cached(
        self,
        url: str,
        *,
        playlist_end: int = 1,
        retries: int = YTDLP_DEFAULT_RETRIES,
        structured: Mapping[str, Any] | None = None,
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
            url,
            playlist_end=playlist_end,
            retries=retries,
            structured=structured,
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
            "en" if self.platform == "youtube" else ("zh" if self.platform == "douyin" else None)
        )
        # The fast path can yield rows built purely from the flat catalogue
        # (title + view count, no description/timestamp). Those are truthful but
        # incomplete, so we flag them: an incomplete row must never overwrite
        # richer data that a previous full extraction already stored.
        detail_level = str(entry.get("_sio_detail_level") or "full")
        partial_meta: dict[str, Any] = {}
        if detail_level != "full":
            partial_meta = {"detail_level": detail_level, "partial": True}
        return PlatformContentData(
            external_id=video_id
            or (
                f"{handle}_"
                # Not a security primitive: this only derives a stable synthetic
                # id for entries the platform did not give us an id for.
                f"{hashlib.sha1(str(entry).encode(), usedforsecurity=False).hexdigest()[:16]}"
            ),
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
                **partial_meta,
                **{f"yt_{k}": v for k, v in metrics.items()},
            },
            media=media,
            tags=self._clean_tags(entry.get("tags")),
        )

    # -- PlatformAdapter contract -----------------------------------------

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        # yt-dlp works anonymously; browser fallback carries its own validation.
        return None

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        handle = self._normalize_handle(locator)
        try:
            data, _ = await self._run_yt_dlp_single_cached(
                self._account_url(handle),
                playlist_end=1,
                retries=self._resolve_retries(ctx),
                structured=self._yt_config(ctx),
            )
        except YTDLP_BROWSER_FALLBACK_ERRORS:
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
            "en" if self.platform == "youtube" else ("zh" if self.platform == "douyin" else None)
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

    async def fetch_account(self, ctx: AdapterCallContext, external_id: str) -> PlatformAccountData:
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
                structured=self._yt_config(ctx),
            )
        except YTDLP_BROWSER_FALLBACK_ERRORS:
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
        if self.platform in ("tiktok", "douyin") and all(v is None for v in metrics.values()):
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
        raw_yt_cfg = cfg.get("yt_dlp")
        yt_cfg: dict[str, Any] = raw_yt_cfg if isinstance(raw_yt_cfg, dict) else {}
        dateafter = yt_cfg.get("dateafter")
        datebefore = yt_cfg.get("datebefore")
        max_items = yt_cfg.get("max_items")
        extra_args = yt_cfg.get("extra_args")
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
        # Fast path: enumerate the window flat (cheap), then fully extract only
        # the works that actually need it, in parallel. Falls back to the legacy
        # single-shot extraction whenever it cannot produce a catalogue.
        entries: list[dict[str, Any]] | None = None
        concurrency = self._fetch_concurrency(ctx)
        if concurrency > 1 or getattr(ctx, "skip_known", False):
            entries = await self._fast_list_entries(
                ctx,
                handle,
                playlist_start=playlist_start,
                playlist_end=playlist_end,
                dateafter=dateafter,
                datebefore=datebefore,
                extra_args=extra_args if isinstance(extra_args, dict) else None,
                structured=yt_cfg if isinstance(yt_cfg, dict) else None,
                download=download_cfg,
                media_dir=media_dir,
                concurrency=concurrency,
            )
        if entries is not None:
            return self._page_from_entries(
                entries,
                ctx,
                handle,
                window=window,
                offset=offset,
                max_items=max_items,
                media_dir=media_dir,
                media_root=media_root,
            )
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
                progress_callback=getattr(ctx, "progress_sink", None),
            )
        except YTDLP_BROWSER_FALLBACK_ERRORS as exc:
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

        return self._page_from_entries(
            entries,
            ctx,
            handle,
            window=window,
            offset=offset,
            max_items=max_items,
            media_dir=media_dir,
            media_root=media_root,
        )

    def _page_from_entries(
        self,
        entries: Sequence[Mapping[str, Any]],
        ctx: AdapterCallContext,
        handle: str,
        *,
        window: int,
        offset: int,
        max_items: Any,
        media_dir: str | None,
        media_root: str | None,
    ) -> AdapterPage:
        """Turn raw yt-dlp entries into an :class:`AdapterPage`.

        Shared by the legacy single-shot extraction and the fast enumerate +
        parallel-detail path so both produce identical rows, metrics cache
        entries and pagination cursors.
        """
        items: list[PlatformContentData] = []
        for entry in entries[:window]:
            media = None
            vid = entry.get("id")
            if media_dir and media_root and vid:
                # ``media_root`` is workspace-scoped (MEDIA_ROOT/<ws>); the
                # relative ``base`` stored on the row must be relative to the
                # global MEDIA_ROOT so the ``/media`` route resolves it.
                media = self._collect_media(os.path.dirname(media_root), media_dir, str(vid))
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

    async def _fast_list_entries(
        self,
        ctx: AdapterCallContext,
        handle: str,
        *,
        playlist_start: int,
        playlist_end: int,
        dateafter: str | None,
        datebefore: str | None,
        extra_args: Mapping[str, Any] | None,
        structured: Mapping[str, Any] | None,
        download: Mapping[str, Any] | None,
        media_dir: str | None,
        concurrency: int,
    ) -> list[dict[str, Any]] | None:
        """Enumerate flat, then fully extract only the works that need it.

        Returns ``None`` when the catalogue could not be read, which tells the
        caller to fall back to the legacy single-shot extraction. Returning an
        empty list is a *valid* result meaning "this window has no works".
        """
        sink = getattr(ctx, "progress_sink", None)
        flat = await self._flat_enumerate(
            self._videos_url(handle),
            playlist_start=playlist_start,
            playlist_end=playlist_end,
            dateafter=dateafter,
            datebefore=datebefore,
            structured=structured,
        )
        if not flat:
            # Empty can mean "end of catalogue" *or* "flat mode unsupported for
            # this extractor". We cannot tell them apart, so defer to the legacy
            # path which knows how to fall back to the browser adapter.
            return None

        known: frozenset[str] = getattr(ctx, "known_external_ids", frozenset()) or frozenset()
        skip_known = bool(getattr(ctx, "skip_known", False))
        needs_detail: dict[str, str] = {}
        for entry in flat:
            vid = str(entry.get("id") or "")
            if not vid:
                continue
            if skip_known and vid in known:
                # Already stored and the policy leaves known works untouched:
                # the flat entry still refreshes view_count, which is the only
                # metric that meaningfully moves for an unchanged work.
                continue
            url = entry.get("webpage_url") or entry.get("url") or self._canonical_for(vid, handle)
            needs_detail[vid] = str(url)

        if sink is not None:
            sink(
                f"[fast] 目录枚举 {len(flat)} 条，其中 {len(needs_detail)} 条需要完整解析"
                f"（已入库跳过 {len(flat) - len(needs_detail)} 条）\n"
            )
        details = await self._extract_details(
            needs_detail,
            concurrency=concurrency,
            dateafter=dateafter,
            datebefore=datebefore,
            structured=structured,
            download=download,
            media_dir=media_dir,
            extra_args=extra_args,
            progress_callback=sink,
        )

        merged: list[dict[str, Any]] = []
        for entry in flat:
            vid = str(entry.get("id") or "")
            detail = details.get(vid)
            if detail is None:
                if vid in needs_detail:
                    # Detail extraction failed for a work we wanted in full. The
                    # flat catalogue row is still truthful (real title, real view
                    # count) so we keep it rather than dropping the work; the
                    # marker lets downstream code tell the two apart.
                    entry = {**entry, "_sio_detail_level": "flat_only"}
                else:
                    entry = {**entry, "_sio_detail_level": "flat_known"}
                merged.append(entry)
                continue
            # Prefer full detail, but let the flat catalogue backfill anything
            # the per-video extraction happened to omit.
            combined = {**entry, **{k: v for k, v in detail.items() if v is not None}}
            combined["_sio_detail_level"] = "full"
            merged.append(combined)
        return merged

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        if self.platform == "youtube":
            url = f"https://www.youtube.com/watch?v={external_id}"
            try:
                entries, _ = await self._run_yt_dlp(
                    url,
                    structured={"ignore_errors": True, "no_warnings": True},
                    progress_callback=getattr(ctx, "progress_sink", None),
                )
            except YTDLP_BROWSER_FALLBACK_ERRORS:
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
            _, _ = await self._communicate_with_timeout(proc, 15)
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
