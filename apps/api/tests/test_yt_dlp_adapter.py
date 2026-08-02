"""Offline tests for the yt-dlp universal adapter.

These tests never touch the network: yt-dlp's subprocess call is replaced with
canned JSON, exactly mirroring the structure yt-dlp emits for each platform.
They verify (a) field mapping into the platform contract and (b) that the
browser-simulation adapter is wired in as a fallback when yt-dlp yields nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.adapters.platforms.base import AdapterPage, PlatformContentData
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
    return SimpleNamespace(
        observed_at=datetime(2026, 1, 1, tzinfo=UTC), config={}, request_id="r1"
    )


def _bind(adapter: YtDlpAdapter, video_entries, channel_entries):
    async def _fake(
        url,
        *,
        playlist_start=None,
        playlist_end=None,
        dateafter=None,
        datebefore=None,
        extra_args=None,
    ):
        if "videos" in url:
            return list(video_entries), ""
        return list(channel_entries), ""

    adapter._run_yt_dlp = _fake  # type: ignore[assignment]

    # Account-level methods use --dump-single-json; the channel metadata lives
    # at the top level of that object (not in the per-video entries).
    single = dict(channel_entries[0]) if channel_entries else {}
    single.setdefault("playlist_count", 500)
    async def _fake_single(url, *, playlist_end=1):
        return single, ""

    adapter._run_yt_dlp_single = _fake_single  # type: ignore[assignment]


def test_extract_thumbnail_variants():
    adapter = YouTubeYtDlpAdapter()
    assert (
        adapter._extract_thumbnail({"thumbnail": "http://x/a.jpg"}) == "http://x/a.jpg"
    )
    assert (
        adapter._extract_thumbnail({"thumbnail": {"url": "http://x/b.jpg"}})
        == "http://x/b.jpg"
    )
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
    page = await adapter.list_contents(
        ctx, "guitar_daily", published_after=None, cursor=None, page_size=5
    )
    content = page.items[0]
    assert content.external_id == "7372846510293"
    assert content.canonical_url == "https://www.tiktok.com/@guitar_daily/video/7372846510293"
    analytics = await adapter.fetch_content_analytics(ctx, [content.external_id])
    assert analytics[0].metrics["like_count"] == 98765
    assert analytics[0].metrics["share_count"] == 1234


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
    async def _empty(url, *, playlist_end=None):  # type: ignore[assignment]
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
        async def list_contents(self, ctx, external_account_id, *, published_after, cursor, page_size):
            fallback_calls["n"] += 1
            return AdapterPage(items=(), next_cursor=None)

    adapter._fb = _StubFallback()  # type: ignore[assignment]

    async def _empty(url, *, playlist_start=None, playlist_end=None, dateafter=None,
                    datebefore=None, extra_args=None):
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
    ):
        captured["dateafter"] = dateafter
        captured["datebefore"] = datebefore
        captured["extra_args"] = extra_args
        captured["playlist_start"] = playlist_start
        captured["playlist_end"] = playlist_end
        start = (playlist_start or 1) - 1
        end = playlist_end if playlist_end is not None else len(all_entries)
        return all_entries[start:end], ""

    adapter._run_yt_dlp = _windowed  # type: ignore[assignment]
    return captured


@pytest.mark.asyncio
async def test_list_contents_paginates_past_default_ceiling():
    adapter = YouTubeYtDlpAdapter()
    # 120-video playlist; previously capped at ~50 in a single call.
    all_entries = [
        {**YOUTUBE_VIDEO, "id": f"vid{i}", "title": f"Video {i}"} for i in range(120)
    ]
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
    await adapter.list_contents(
        ctx, "olympics", published_after=None, cursor=None, page_size=10
    )
    assert captured["extra_args"] == {"match_filter": "test", "geo_bypass": True}
