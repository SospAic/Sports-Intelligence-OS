"""Unit tests for ``PlatformSyncExecutor._metrics_from_metadata``.

Browser adapters cannot call a structured analytics API, so they stash
interaction counts in ``ContentItem.metadata_json`` during listing. The sync
synthesize path harvests those into ``ContentSnapshot`` rows so #61/#62 are not
blank. These tests lock in the alias normalisation (digg->like, play->view,
...).
"""
from datetime import UTC, datetime

from app.adapters.platforms.base import (
    PlatformContentData,
    PlatformMetricsData,
    parse_compact_count,
)
from app.services.sync import PlatformSyncExecutor


def test_douyin_api_intercept_metadata_yields_full_metrics() -> None:
    meta = {
        "method": "browser_api_intercept",
        "digg_count": 1234,
        "comment_count": 56,
        "share_count": 7,
        "play_count": 98765,
    }
    out = PlatformSyncExecutor._metrics_from_metadata(meta)
    assert out == {
        "view_count": 98765,
        "like_count": 1234,
        "comment_count": 56,
        "share_count": 7,
    }


def test_bilibili_metadata_yields_view_and_comment() -> None:
    meta = {
        "method": "browser_dom_scrape",
        "view_count": 555000,
        "comment_count": 321,
    }
    out = PlatformSyncExecutor._metrics_from_metadata(meta)
    assert out == {"view_count": 555000, "comment_count": 321}


def test_play_count_maps_to_view_count() -> None:
    assert PlatformSyncExecutor._metrics_from_metadata({"play_count": 42}) == {
        "view_count": 42
    }


def test_digg_count_maps_to_like_count() -> None:
    assert PlatformSyncExecutor._metrics_from_metadata({"digg_count": 9}) == {
        "like_count": 9
    }


def test_string_counts_are_parsed() -> None:
    out = PlatformSyncExecutor._metrics_from_metadata(
        {"play_count": "1.2万", "comment_count": "3.4K"}
    )
    assert out == {"view_count": 12000, "comment_count": 3400}


def test_repost_count_maps_to_share_count() -> None:
    assert PlatformSyncExecutor._metrics_from_metadata({"repost_count": 88}) == {
        "share_count": 88
    }


def test_favorite_count_is_preserved() -> None:
    assert PlatformSyncExecutor._metrics_from_metadata({"favorite_count": 11}) == {
        "favorite_count": 11
    }


def test_missing_metadata_yields_empty() -> None:
    assert PlatformSyncExecutor._metrics_from_metadata(None) == {}
    assert PlatformSyncExecutor._metrics_from_metadata({}) == {}


def test_public_catalogue_metrics_are_not_labelled_missing() -> None:
    content = PlatformContentData(
        external_id="post-1",
        account_external_id="creator",
        content_type="video",
        title="Public post",
        description=None,
        published_at=None,
        duration_seconds=None,
        canonical_url="https://example.com/post-1",
        cover_url=None,
        language="en",
        status="public",
        source_kind="live",
        provider="tiktok_browser",
        fetched_at=datetime.now(UTC),
        metadata={"view_count": 1200, "like_count": 80},
    )
    empty_analytics = PlatformMetricsData(
        external_id="post-1",
        captured_at=content.fetched_at,
        metrics={},
        source_kind="live",
        provider="tiktok_browser",
        fetched_at=content.fetched_at,
        unavailable_metrics=("view_count", "like_count"),
    )
    assert (
        PlatformSyncExecutor._content_metrics_state(
            content, empty_analytics, analytics_failed=False
        )
        == "partial"
    )
    assert (
        PlatformSyncExecutor._content_metrics_state(
            content, None, analytics_failed=True
        )
        == "partial"
    )


def test_bool_values_are_ignored() -> None:
    # Booleans are subclasses of int; they must not be treated as counts.
    out = PlatformSyncExecutor._metrics_from_metadata(
        {"view_count": True, "like_count": False}
    )
    assert out == {}


def test_parse_compact_count_handles_english_suffixes() -> None:
    assert parse_compact_count("1.2M views") == 1_200_000
    assert parse_compact_count("456K") == 456_000
    assert parse_compact_count("1,234,567") == 1_234_567
    assert parse_compact_count("789") == 789


def test_parse_compact_count_handles_chinese_suffixes() -> None:
    # Douyin/Bilibili UIs use 万 (1e4) / 亿 (1e8) / 万亿 (1e12).
    assert parse_compact_count("1.2万") == 12_000
    assert parse_compact_count("3.4亿") == 340_000_000
    assert parse_compact_count("1.2万亿") == 1_200_000_000_000
    assert parse_compact_count("5.5万次播放") == 55_000


def test_parse_compact_count_rejects_garbage() -> None:
    assert parse_compact_count("") is None
    assert parse_compact_count(None) is None
    assert parse_compact_count("not a number") is None
