"""Offline tests for the yt-dlp universal adapter.

These tests never touch the network: yt-dlp's subprocess call is replaced with
canned JSON, exactly mirroring the structure yt-dlp emits for each platform.
They verify (a) field mapping into the platform contract and (b) that yt-dlp is
the *primary* source — the browser-simulation adapter is only ever used as a
fallback when yt-dlp yields *nothing* (empty first page) or hard-fails. A
partial window (fewer items than requested but non-empty) is treated as the
end of the catalogue and does NOT trigger a browser switch.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.adapters.platforms.base import (
    AdapterPage,
    PlatformAccountData,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)
from app.adapters.platforms.yt_dlp import (
    DouyinYtDlpAdapter,
    TikTokYtDlpAdapter,
    YouTubeYtDlpAdapter,
    YtDlpAdapter,
)

YOUTUBE_VIDEO = {
    "id": "dQw4w9WgXcQ",
    "title": "Rocket League Greatest Goals",
    "description": "A long description of the video.",
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "duration": 212.0,
    "view_count": 1234567,
    "like_count": 45000,
    "comment_count": 1200,
    "repost_count": 300,
    "timestamp": 1700000000,
    "channel": "Olympics",
    "channel_id": "UC_zsYzIVBwSBj880Fs8z2Tg",
    "channel_follower_count": 12300000,
    "uploader": "Olympics",
    "uploader_id": "@olympics",
    "tags": ["sport", "olympics"],
}

YOUTUBE_CHANNEL = {
    "id": "UC_zsYzIVBwSJj880Fs8z2Tg",
    "title": "Olympics",
    "channel": "Olympics",
    "uploader": "Olympics",
    "channel_id": "UC_zsYzIVBwSJj880Fs8z2Tg",
    "channel_follower_count": 12300000,
    "description": "The Olympic Channel.",
    "thumbnail": "https://yt3.ggpht.com/avatar.jpg",
}

TIKTOK_VIDEO = {
    "id": "7372846510293",
    "title": "Day 3 of learning guitar",
    "description": "caption text",
    "webpage_url": "https://www.tiktok.com/@guitar_daily/video/7372846510293",
    "thumbnail": "https://p16-sign.tiktokcdn.com/cover.jpg",
    "duration": 45.0,
    "view_count": 1234567,
    "like_count": 98765,
    "comment_count": 432,
    "repost_count": 1234,
    "timestamp": 1716000000,
    "uploader": "guitar_daily",
    "uploader_id": "guitar_daily",
}


def make_ctx() -> SimpleNamespace:
    return SimpleNamespace(observed_at=datetime(2026, 1, 1, tzinfo=UTC), config={}, request_id="r1")


def _bind(adapter: YtDlpAdapter, video_entries, channel_entries):
    async def _fake(
        url,
        *,
        playlist_start=None,
        playlist_end=None,
        dateafter=None,
        datebefore=None,
        extra_args=None,
        structured=None,
        download=None,
        media_dir=None,
    ):
        if "videos" in url:
            return list(video_entries), ""
        return list(channel_entries), ""

    adapter._run_yt_dlp = _fake  # type: ignore[assignment]

    # Account-level methods use --dump-single-json; the channel metadata lives
    # at the top level of that object (not in the per-video entries).
    single = dict(channel_entries[0]) if channel_entries else {}
    single.setdefault("playlist_count", 500)

    async def _fake_single(url, *, playlist_end=1, **kwargs):
        return single, ""

    adapter._run_yt_dlp_single = _fake_single  # type: ignore[assignment]


def test_extract_thumbnail_variants():
    adapter = YouTubeYtDlpAdapter()
    assert adapter._extract_thumbnail({"thumbnail": "http://x/a.jpg"}) == "http://x/a.jpg"
    assert adapter._extract_thumbnail({"thumbnail": {"url": "http://x/b.jpg"}}) == "http://x/b.jpg"
    assert (
        adapter._extract_thumbnail(
            {
                "thumbnails": [
                    {"url": "http://x/s.jpg", "width": 120},
                    {"url": "http://x/l.jpg", "width": 640},
                ]
            }
        )
        == "http://x/l.jpg"
    )
    assert adapter._extract_thumbnail({}) is None


def test_parse_timestamp_prefers_epoch():
    adapter = YouTubeYtDlpAdapter()
    assert adapter._parse_timestamp({"timestamp": 1700000000}) == datetime(
        2023, 11, 14, 22, 13, 20, tzinfo=UTC
    )
    assert adapter._parse_timestamp({"upload_date": "20231114"}) == datetime(
        2023, 11, 14, tzinfo=UTC
    )
    assert adapter._parse_timestamp({}) is None


def test_metrics_from_entry_maps_share_to_repost():
    adapter = YouTubeYtDlpAdapter()
    metrics = adapter._metrics_from_entry(YOUTUBE_VIDEO)
    assert metrics == {
        "view_count": 1234567,
        "like_count": 45000,
        "comment_count": 1200,
        "share_count": 300,
    }


@pytest.mark.asyncio
async def test_youtube_resolve_and_analytics():
    adapter = YouTubeYtDlpAdapter()
    _bind(adapter, [YOUTUBE_VIDEO], [YOUTUBE_CHANNEL])
    ctx = make_ctx()
    acc = await adapter.resolve_account(ctx, "@olympics")
    assert acc.external_id == "olympics"
    assert acc.display_name == "Olympics"
    assert acc.avatar_url == "https://yt3.ggpht.com/avatar.jpg"
    assert acc.metadata["channel_id"] == "UC_zsYzIVBwSJj880Fs8z2Tg"

    analytics = await adapter.fetch_account_analytics(ctx, "olympics")
    assert analytics.metrics["follower_count"] == 12300000
    # playlist_count is present in the single-json object → video_count is real.
    assert analytics.metrics["video_count"] == 500
    assert "video_count" not in analytics.unavailable_metrics


@pytest.mark.asyncio
async def test_account_stage_reuses_single_yt_dlp_run():
    """``resolve_account`` and ``fetch_account_analytics`` both query the same
    channel URL during one sync run. The per-instance memo must collapse them
    into a single yt-dlp invocation — a redundant second subprocess per account
    is exactly the extra latency we removed (an account sync should run at
    yt-dlp's native speed, not pay for the channel object twice)."""

    from unittest.mock import AsyncMock

    adapter = YouTubeYtDlpAdapter()
    single = dict(YOUTUBE_CHANNEL)
    single.setdefault("playlist_count", 500)
    fake = AsyncMock(return_value=(single, ""))
    adapter._run_yt_dlp_single = fake  # type: ignore[assignment]
    ctx = make_ctx()

    await adapter.resolve_account(ctx, "@olympics")
    await adapter.fetch_account_analytics(ctx, "olympics")

    assert fake.await_count == 1


@pytest.mark.asyncio
async def test_youtube_list_and_content_analytics_cache():
    adapter = YouTubeYtDlpAdapter()
    _bind(adapter, [YOUTUBE_VIDEO], [YOUTUBE_CHANNEL])
    ctx = make_ctx()
    page = await adapter.list_contents(
        ctx, "olympics", published_after=None, cursor=None, page_size=10
    )
    assert isinstance(page, AdapterPage)
    assert len(page.items) == 1
    content = page.items[0]
    assert content.external_id == "dQw4w9WgXcQ"
    assert content.title == "Rocket League Greatest Goals"
    assert content.duration_seconds == 212.0
    assert content.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert content.cover_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert content.published_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    # Exact metrics stashed in metadata for transparency.
    assert content.metadata["yt_view_count"] == 1234567

    analytics = await adapter.fetch_content_analytics(ctx, [content.external_id])
    assert analytics[0].metrics["view_count"] == 1234567
    assert analytics[0].metrics["like_count"] == 45000
    assert analytics[0].metrics["comment_count"] == 1200
    assert analytics[0].metrics["share_count"] == 300
    assert analytics[0].unavailable_metrics == ()


@pytest.mark.asyncio
async def test_tiktok_canonical_url_and_metrics():
    adapter = TikTokYtDlpAdapter()
    _bind(adapter, [TIKTOK_VIDEO], [TIKTOK_VIDEO])
    ctx = make_ctx()
    # page_size == returned count → full window, so the yt-dlp result is used
    # directly (the tiktok/douyin partial-window browser fallback stays idle).
    page = await adapter.list_contents(
        ctx, "guitar_daily", published_after=None, cursor=None, page_size=1
    )
    content = page.items[0]
    assert content.external_id == "7372846510293"
    assert content.canonical_url == "https://www.tiktok.com/@guitar_daily/video/7372846510293"
    analytics = await adapter.fetch_content_analytics(ctx, [content.external_id])
    assert analytics[0].metrics["like_count"] == 98765
    assert analytics[0].metrics["share_count"] == 1234


@pytest.mark.asyncio
async def test_tiktok_analytics_partial_fetch_is_not_degraded():
    # TikTok/Douyin user pages via yt-dlp rarely expose follower/video counts,
    # but the fetch still returns a real account object. The adapter must report
    # ``analytics_fetched=True`` and surface the missing fields via
    # ``unavailable_metrics`` rather than signalling a failed extraction. The
    # browser fallback (used to recover the metrics) is stubbed so the test
    # stays offline and the yt-dlp-only result is asserted.
    adapter = TikTokYtDlpAdapter()
    profile = {
        "id": "MS4wLjABAAAAexample",
        "title": "guitar_daily",
        "uploader": "guitar_daily",
        "webpage_url": "https://www.tiktok.com/@guitar_daily",
    }

    async def _fake_single(url, *, playlist_end=1, **kwargs):
        return profile, ""

    adapter._run_yt_dlp_single = _fake_single  # type: ignore[assignment]

    class _StubFallback:
        async def fetch_account_analytics(self, ctx, external_id):
            # Browser also comes up empty (offline); yt-dlp's channel object is
            # still treated as a successful fetch.
            return PlatformMetricsData(
                external_id=external_id,
                captured_at=ctx.observed_at,
                metrics={},
                source_kind="live",
                provider="tiktok_browser",
                fetched_at=ctx.observed_at,
                unavailable_metrics=(),
                metadata={"method": "browser_scrape"},
            )

    adapter._fb = _StubFallback()  # type: ignore[assignment]
    ctx = make_ctx()
    analytics = await adapter.fetch_account_analytics(ctx, "@guitar_daily")
    assert analytics.metadata.get("analytics_fetched") is True
    assert analytics.metrics["follower_count"] is None
    assert analytics.metrics["video_count"] is None
    assert analytics.metrics["total_view_count"] is None
    assert {"follower_count", "video_count", "total_view_count"}.issubset(
        set(analytics.unavailable_metrics)
    )


@pytest.mark.asyncio
async def test_tiktok_analytics_browser_fallback_captures_metrics():
    # When yt-dlp fetches the TikTok channel but exposes no account metrics,
    # the adapter must delegate to the browser adapter and *merge* the scraped
    # follower / like / video counts back into the result (instead of leaving
    # them permanently unavailable). The merged metrics must keep
    # ``analytics_fetched=True`` so the sync is not misreported as degraded.
    adapter = TikTokYtDlpAdapter()
    profile = {
        "id": "MS4wLjABAAAAexample",
        "title": "guitar_daily",
        "uploader": "guitar_daily",
        "webpage_url": "https://www.tiktok.com/@guitar_daily",
    }

    async def _fake_single(url, *, playlist_end=1, **kwargs):
        return profile, ""

    adapter._run_yt_dlp_single = _fake_single  # type: ignore[assignment]

    class _StubFallback:
        async def fetch_account_analytics(self, ctx, external_id):
            return PlatformMetricsData(
                external_id=external_id,
                captured_at=ctx.observed_at,
                metrics={
                    "follower_count": 61600,
                    "total_like_count": 1300000,
                    "video_count": 201,
                },
                source_kind="live",
                provider="tiktok_browser",
                fetched_at=ctx.observed_at,
                unavailable_metrics=(),
                metadata={"method": "browser_scrape"},
            )

    adapter._fb = _StubFallback()  # type: ignore[assignment]
    ctx = make_ctx()
    analytics = await adapter.fetch_account_analytics(ctx, "@guitar_daily")
    assert analytics.metadata.get("analytics_fetched") is True
    assert analytics.metadata.get("analytics_source") == "browser"
    assert analytics.metrics["follower_count"] == 61600
    assert analytics.metrics["total_like_count"] == 1300000
    assert analytics.metrics["video_count"] == 201
    # TikTok exposes no total view count even via the browser, so it stays
    # unavailable rather than fabricated.
    assert analytics.metrics["total_view_count"] is None
    assert "total_view_count" in analytics.unavailable_metrics


@pytest.mark.asyncio
async def test_tiktok_analytics_transient_failure_reports_not_fetched():
    # A genuinely empty yt-dlp result (transient failure) must be reported as
    # ``analytics_fetched=False`` so the sync engine can still flag it degraded.
    # The browser fallback is stubbed to also fail (offline) so the test stays
    # hermetic and the degraded signal is preserved.
    adapter = TikTokYtDlpAdapter()

    async def _fake_single(url, *, playlist_end=1, **kwargs):
        raise TransientAdapterError("yt-dlp timed out")

    adapter._run_yt_dlp_single = _fake_single  # type: ignore[assignment]

    class _StubFallback:
        async def fetch_account_analytics(self, ctx, external_id):
            return PlatformMetricsData(
                external_id=external_id,
                captured_at=ctx.observed_at,
                metrics={},
                source_kind="live",
                provider="tiktok_browser",
                fetched_at=ctx.observed_at,
                unavailable_metrics=(),
                metadata={"method": "browser_scrape"},
            )

    adapter._fb = _StubFallback()  # type: ignore[assignment]
    ctx = make_ctx()
    analytics = await adapter.fetch_account_analytics(ctx, "@guitar_daily")
    assert analytics.metadata.get("analytics_fetched") is False
    assert analytics.metrics["follower_count"] is None
    assert analytics.metrics["video_count"] is None


@pytest.mark.asyncio
async def test_tiktok_partial_window_does_not_fallback():
    adapter = TikTokYtDlpAdapter()
    # yt-dlp returns only one of the requested 5 on the FIRST page. Under the
    # yt-dlp-primary policy a partial (non-empty) window is treated as the end
    # of the catalogue — NOT a trigger for the browser fallback — so the single
    # yt-dlp item is returned directly and pagination stops.
    _bind(adapter, [TIKTOK_VIDEO], [TIKTOK_VIDEO])
    ctx = make_ctx()
    fallback_calls = {"n": 0}

    class _CountingFallback:
        async def list_contents(
            self, ctx, external_account_id, *, published_after, cursor, page_size
        ):
            fallback_calls["n"] += 1
            raise AssertionError("browser fallback must not fire on a partial window")

    adapter._fb = _CountingFallback()  # type: ignore[assignment]
    page = await adapter.list_contents(
        ctx, "guitar_daily", published_after=None, cursor=None, page_size=5
    )
    assert len(page.items) == 1
    assert page.items[0].external_id == "7372846510293"
    assert page.next_cursor is None
    assert fallback_calls["n"] == 0


@pytest.mark.asyncio
async def test_run_yt_dlp_single_null_payload_is_safe():
    """yt-dlp emits a literal ``null`` for profiles it cannot resolve (e.g.
    Douyin). The single-json runner must return an empty dict — never crash
    with ``None.get(...)`` downstream (the root cause of the prior
    ``unexpected_sync_error`` on Douyin accounts)."""
    adapter = TikTokYtDlpAdapter()

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"null\n", b""

    async def _fake_exec(*args, **kwargs):
        return _FakeProc()

    real = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = _fake_exec  # type: ignore[assignment]
    try:
        obj, err = await adapter._run_yt_dlp_single("https://example.com/x")
    finally:
        asyncio.create_subprocess_exec = real
    assert obj == {}
    assert err == ""


@pytest.mark.asyncio
async def test_resolve_account_null_profile_falls_back_gracefully():
    """When yt-dlp cannot resolve a profile (yields ``null`` → ``{}`` after the
    safe guard) the adapter must fall back to the browser adapter rather than
    raise. This is the exact path that previously crashed with
    ``'NoneType' object has no attribute 'get'`` on Douyin accounts."""
    adapter = DouyinYtDlpAdapter()

    async def _empty_single(url, *, playlist_end=1, **kwargs):  # type: ignore[assignment]
        return {}, ""

    adapter._run_yt_dlp_single = _empty_single  # type: ignore[assignment]

    resolved = SimpleNamespace(captured=False)

    class _StubFallback:
        async def resolve_account(self, ctx, locator):
            resolved.captured = True
            return PlatformAccountData(
                external_id=locator,
                username=locator,
                display_name="From Browser",
                profile_url="https://example.com/" + locator,
                avatar_url=None,
                description=None,
                country=None,
                language="zh",
                is_verified=None,
                source_kind="live",
                provider="stub",
                fetched_at=ctx.observed_at,
            )

    adapter._fb = _StubFallback()  # type: ignore[assignment]
    ctx = make_ctx()
    acc = await adapter.resolve_account(ctx, "theolympics")
    assert resolved.captured is True
    assert acc.display_name == "From Browser"


class _StubFallback:
    """Minimal browser adapter stub used to prove fallback wiring."""

    async def list_contents(self, ctx, external_account_id, *, published_after, cursor, page_size):
        return AdapterPage(
            items=(
                PlatformContentData(
                    external_id="fallback1",
                    account_external_id=external_account_id,
                    content_type="video",
                    title="Fallback item",
                    description=None,
                    published_at=None,
                    duration_seconds=None,
                    canonical_url="https://example.com/fallback1",
                    cover_url=None,
                    language=None,
                    status="public",
                    source_kind="live",
                    provider="stub",
                    fetched_at=ctx.observed_at,
                ),
            ),
            next_cursor=None,
        )


@pytest.mark.asyncio
async def test_fallback_used_when_yt_dlp_empty():
    adapter = DouyinYtDlpAdapter()

    # yt-dlp yields nothing → must delegate to the browser adapter.
    async def _empty(
        url,
        *,
        playlist_start=None,
        playlist_end=None,
        dateafter=None,
        datebefore=None,
        extra_args=None,
        structured=None,
        download=None,
        media_dir=None,
    ):  # type: ignore[assignment]
        return [], "ERROR: unsupported"

    adapter._run_yt_dlp = _empty
    adapter._fb = _StubFallback()  # type: ignore[assignment]
    ctx = make_ctx()
    page = await adapter.list_contents(
        ctx, "some_douyin", published_after=None, cursor=None, page_size=10
    )
    assert page.items[0].external_id == "fallback1"


@pytest.mark.asyncio
async def test_empty_trailing_page_does_not_fallback():
    adapter = DouyinYtDlpAdapter()
    fallback_calls = {"n": 0}

    class _StubFallback:
        async def list_contents(
            self, ctx, external_account_id, *, published_after, cursor, page_size
        ):
            fallback_calls["n"] += 1
            return AdapterPage(items=(), next_cursor=None)

    adapter._fb = _StubFallback()  # type: ignore[assignment]

    async def _empty(
        url,
        *,
        playlist_start=None,
        playlist_end=None,
        dateafter=None,
        datebefore=None,
        extra_args=None,
        structured=None,
        download=None,
        media_dir=None,
    ):
        return [], ""

    adapter._run_yt_dlp = _empty  # type: ignore[assignment]
    ctx = make_ctx()
    # A cursor is set → this is a trailing page, not the first request.
    page = await adapter.list_contents(
        ctx, "some_douyin", published_after=None, cursor="50", page_size=50
    )
    assert page.items == ()
    assert page.next_cursor is None
    assert fallback_calls["n"] == 0


def _make_windowed_adapter(adapter: YtDlpAdapter, all_entries, captured=None):
    """Replace yt-dlp with a stub that honours playlist_start/end windowing so
    we can exercise cursor pagination without the subprocess."""
    captured = captured if captured is not None else {}

    async def _windowed(
        url,
        *,
        playlist_start=None,
        playlist_end=None,
        dateafter=None,
        datebefore=None,
        extra_args=None,
        structured=None,
        download=None,
        media_dir=None,
    ):
        captured["dateafter"] = dateafter
        captured["datebefore"] = datebefore
        captured["extra_args"] = extra_args
        captured["playlist_start"] = playlist_start
        captured["playlist_end"] = playlist_end
        captured["structured"] = structured
        captured["download"] = download
        captured["media_dir"] = media_dir
        start = (playlist_start or 1) - 1
        end = playlist_end if playlist_end is not None else len(all_entries)
        return all_entries[start:end], ""

    adapter._run_yt_dlp = _windowed  # type: ignore[assignment]
    # Stub the browser fallback so param-passthrough tests (which feed an empty
    # window to exercise the call args) don't attempt to launch a real browser.
    adapter._fb = _StubFallback()  # type: ignore[assignment]
    return captured


@pytest.mark.asyncio
async def test_list_contents_paginates_past_default_ceiling():
    adapter = YouTubeYtDlpAdapter()
    # 120-video playlist; previously capped at ~50 in a single call.
    all_entries = [{**YOUTUBE_VIDEO, "id": f"vid{i}", "title": f"Video {i}"} for i in range(120)]
    _make_windowed_adapter(adapter, all_entries)

    ctx = make_ctx()
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while pages < 10:
        page = await adapter.list_contents(
            ctx, "olympics", published_after=None, cursor=cursor, page_size=50
        )
        seen.extend(item.external_id for item in page.items)
        pages += 1
        cursor = page.next_cursor
        if not cursor:
            break

    assert len(seen) == 120
    assert len(set(seen)) == 120  # no duplicates across pages
    assert pages == 3  # 50 + 50 + 20


@pytest.mark.asyncio
async def test_adapter_config_max_items_short_circuits():
    adapter = YouTubeYtDlpAdapter()
    all_entries = [{**YOUTUBE_VIDEO, "id": f"vid{i}"} for i in range(200)]
    captured = _make_windowed_adapter(adapter, all_entries)

    ctx = make_ctx()
    ctx.config = {"yt_dlp": {"max_items": 30, "dateafter": "20240101"}}
    page = await adapter.list_contents(
        ctx, "olympics", published_after=None, cursor=None, page_size=50
    )
    assert len(page.items) == 30
    # Short-circuited: no further pages even though the playlist is larger.
    assert page.next_cursor is None
    assert captured["dateafter"] == "20240101"


@pytest.mark.asyncio
async def test_published_after_becomes_dateafter():
    adapter = YouTubeYtDlpAdapter()
    captured = _make_windowed_adapter(adapter, [])

    ctx = make_ctx()
    await adapter.list_contents(
        ctx,
        "olympics",
        published_after=datetime(2024, 5, 1, tzinfo=UTC),
        cursor=None,
        page_size=10,
    )
    assert captured["dateafter"] == "20240501"


@pytest.mark.asyncio
async def test_extra_args_passthrough_to_yt_dlp():
    adapter = YouTubeYtDlpAdapter()
    captured = _make_windowed_adapter(adapter, [])

    ctx = make_ctx()
    ctx.config = {"yt_dlp": {"extra_args": {"match_filter": "test", "geo_bypass": True}}}
    await adapter.list_contents(ctx, "olympics", published_after=None, cursor=None, page_size=10)
    assert captured["extra_args"] == {"match_filter": "test", "geo_bypass": True}


@pytest.mark.asyncio
async def test_structured_yt_dlp_params_reach_adapter():
    adapter = YouTubeYtDlpAdapter()
    captured = _make_windowed_adapter(adapter, [])

    ctx = make_ctx()
    ctx.config = {
        "yt_dlp": {
            "proxy": "http://proxy:8080",
            "sort": "view_count",
            "geo_bypass": True,
            "age_limit": 18,
            "ignore_errors": True,
            "no_warnings": True,
            "playlist_reverse": False,  # falsy bool → must NOT emit a flag
        }
    }
    await adapter.list_contents(ctx, "olympics", published_after=None, cursor=None, page_size=10)
    # The structured policy is forwarded wholesale to the command builder.
    assert captured["structured"] == {
        "proxy": "http://proxy:8080",
        "sort": "view_count",
        "geo_bypass": True,
        "age_limit": 18,
        "ignore_errors": True,
        "no_warnings": True,
        "playlist_reverse": False,
    }


def test_render_structured_translates_fields_to_flags():
    args = YtDlpAdapter._render_structured(
        {
            "proxy": "http://proxy:8080",
            "sort": "view_count",
            "geo_bypass": True,
            "age_limit": 18,
            "playlist_reverse": False,
            "ignore_errors": False,
            "no_warnings": True,
        }
    )
    assert "--proxy" in args and args[args.index("--proxy") + 1] == "http://proxy:8080"
    assert "--sort" in args and args[args.index("--sort") + 1] == "view_count"
    assert "--age-limit" in args and args[args.index("--age-limit") + 1] == "18"
    # bool True → flag present; bool False → flag absent
    assert "--geo-bypass" in args
    assert "--no-warnings" in args
    assert "--ignore-errors" not in args
    assert "--playlist-reverse" not in args


def test_render_structured_skips_empty_and_none():
    args = YtDlpAdapter._render_structured({"proxy": "", "age_limit": None, "geo_bypass": False})
    assert args == []


def test_any_download_enabled():
    assert YouTubeYtDlpAdapter._any_download_enabled(None) is False
    assert YouTubeYtDlpAdapter._any_download_enabled({}) is False
    assert YouTubeYtDlpAdapter._any_download_enabled({"write_thumbnail": True}) is True
    assert (
        YouTubeYtDlpAdapter._any_download_enabled(
            {"download_video": False, "write_subtitles": False}
        )
        is False
    )
    assert YouTubeYtDlpAdapter._any_download_enabled({"download_video": True}) is True


def test_collect_media_classifies_files(tmp_path):
    video_id = "abc123"
    media_root = tmp_path
    media_dir = tmp_path / "handle"
    d = media_dir / video_id
    d.mkdir(parents=True)
    (d / f"{video_id}.webp").write_bytes(b"x")
    (d / f"{video_id}.zh-Hans.vtt").write_text("x")
    (d / f"{video_id}.en.vtt").write_text("x")
    (d / f"{video_id}.info.json").write_text("{}")
    (d / f"{video_id}.mp4").write_bytes(b"x")

    result = YouTubeYtDlpAdapter._collect_media(str(media_root), str(media_dir), video_id)
    assert result is not None
    assert result["base"] == os.path.join("handle", video_id)
    assert result["thumbnail"] == f"{video_id}.webp"
    assert result["video"] == f"{video_id}.mp4"
    assert result["info_json"] == f"{video_id}.info.json"
    assert {s["lang"] for s in result["subtitles"]} == {"zh-Hans", "en"}


def test_collect_media_none_when_absent(tmp_path):
    assert YouTubeYtDlpAdapter._collect_media(str(tmp_path), str(tmp_path / "h"), "nope") is None


def test_media_route_blocks_path_traversal(tmp_path):
    import app.api.routes.media as media_mod

    original = media_mod.MEDIA_ROOT
    media_mod.MEDIA_ROOT = str(tmp_path)
    try:
        # Enough ".." to climb above MEDIA_ROOT entirely → must be rejected.
        assert media_mod._safe_media_path("ws/h/abc", "../../../../../../../etc/passwd") is None
        ok = media_mod._safe_media_path("ws/h/abc", "abc.mp4")
        assert ok == str(tmp_path / "ws" / "h" / "abc" / "abc.mp4")
    finally:
        media_mod.MEDIA_ROOT = original


def _capture_cmd(adapter, *, single=True, retries=None):
    """Run a yt-dlp command builder with a stubbed subprocess and return the
    exact argv without executing anything on the network."""
    import asyncio

    captured: dict[str, list[str]] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"{}" if single else b"", b""

    async def _fake_exec(*args, **kwargs):
        captured["cmd"] = list(args)
        return _FakeProc()

    real = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = _fake_exec  # type: ignore[assignment]
    loop = asyncio.new_event_loop()
    try:
        if single:
            if retries is None:
                coro = adapter._run_yt_dlp_single("https://example.com/x")
            else:
                coro = adapter._run_yt_dlp_single("https://example.com/x", retries=retries)
            loop.run_until_complete(coro)
        else:
            if retries is None:
                loop.run_until_complete(adapter._run_yt_dlp("https://example.com/x"))
            else:
                loop.run_until_complete(
                    adapter._run_yt_dlp("https://example.com/x", structured={"retries": retries})
                )
    finally:
        asyncio.create_subprocess_exec = real
        loop.close()
    return captured["cmd"]


def test_single_json_defaults_to_ten_retries():
    """yt-dlp's built-in ``--retries`` must be pinned to the default (10) on the
    account-data / analytics single-json invocation when no override is set."""
    adapter = YouTubeYtDlpAdapter()
    cmd = _capture_cmd(adapter, single=True)
    idx = cmd.index("--retries")
    assert cmd[idx + 1] == "10"


def test_single_json_honours_retry_override():
    """An explicit ``retries`` argument must flow through to ``--retries``."""
    adapter = YouTubeYtDlpAdapter()
    cmd = _capture_cmd(adapter, single=True, retries=3)
    idx = cmd.index("--retries")
    assert cmd[idx + 1] == "3"


def test_list_contents_defaults_to_ten_retries():
    """The content-list (per-page) invocation must also pin ``--retries 10`` by
    default, injected into the structured field rendering."""
    adapter = YouTubeYtDlpAdapter()
    cmd = _capture_cmd(adapter, single=False)
    assert "--retries" in cmd
    assert cmd[cmd.index("--retries") + 1] == "10"


def test_resolve_retries_reads_sync_settings_override():
    """``_resolve_retries`` honours ``sync_settings.yt_dlp.retries`` and falls
    back to the module default on missing / invalid values."""
    adapter = YouTubeYtDlpAdapter()

    class _Ctx:
        config = {"yt_dlp": {"retries": 5}}

    assert adapter._resolve_retries(_Ctx()) == 5

    class _CtxDefault:
        config = {}

    assert adapter._resolve_retries(_CtxDefault()) == 10

    class _CtxBad:
        config = {"yt_dlp": {"retries": "not-a-number"}}

    assert adapter._resolve_retries(_CtxBad()) == 10
