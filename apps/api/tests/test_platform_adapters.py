from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterNotImplementedError,
    RateLimitError,
)
from app.adapters.platforms.mock import MockPlatformAdapter
from app.adapters.platforms.registry import build_platform_adapter_registry
from app.adapters.platforms.youtube import YouTubeAdapter


def context(**config: object) -> AdapterCallContext:
    return AdapterCallContext(
        config=config,
        observed_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        request_id="test-request",
    )


@pytest.mark.asyncio
async def test_youtube_official_api_mapping_pagination_and_unavailable_video() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/channels"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC12345678901234567890",
                            "snippet": {
                                "title": "Official Sports Channel",
                                "customUrl": "@officialsports",
                                "publishedAt": "2020-01-01T00:00:00Z",
                                "thumbnails": {
                                    "high": {
                                        "url": "https://img.example/a.jpg",
                                        "width": 800,
                                    }
                                },
                            },
                            "statistics": {
                                "subscriberCount": "1200",
                                "viewCount": "90000",
                                "videoCount": "2",
                            },
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                            "status": {"privacyStatus": "public"},
                        }
                    ]
                },
            )
        if request.url.path.endswith("/playlistItems"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {
                                "title": "Public game",
                                "publishedAt": "2026-07-25T10:00:00Z",
                            },
                            "contentDetails": {
                                "videoId": "video-public",
                                "videoPublishedAt": "2026-07-25T10:00:00Z",
                            },
                        },
                        {
                            "snippet": {
                                "title": "Private video",
                                "publishedAt": "2026-07-25T09:00:00Z",
                            },
                            "contentDetails": {
                                "videoId": "video-private",
                                "videoPublishedAt": "2026-07-25T09:00:00Z",
                            },
                        },
                    ],
                    "nextPageToken": "NEXT",
                },
            )
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "video-public",
                            "snippet": {
                                "channelId": "UC12345678901234567890",
                                "title": "Public game",
                                "publishedAt": "2026-07-25T10:00:00Z",
                            },
                            "contentDetails": {"duration": "PT1M2S"},
                            "status": {"privacyStatus": "public"},
                            "statistics": {"viewCount": "1000"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://www.googleapis.com/youtube/v3/",
    )
    adapter = YouTubeAdapter(client=client, max_attempts=1)
    ctx = context(api_key="official-test-key")
    try:
        account = await adapter.resolve_account(ctx, "@officialsports")
        metrics = await adapter.fetch_account_analytics(ctx, account.external_id)
        page = await adapter.list_contents(
            ctx,
            account.external_id,
            published_after=None,
            cursor=None,
            page_size=50,
        )
    finally:
        await client.aclose()

    assert account.source_kind == "live"
    assert account.provider == "youtube"
    assert metrics.metrics["follower_count"] == 1200
    assert metrics.metrics["following_count"] is None
    assert metrics.metadata["private_youtube_analytics_api_used"] is False
    assert page.next_cursor == "NEXT"
    assert page.items[0].duration_seconds == 62
    assert page.items[1].status == "unavailable"
    assert page.items[1].metadata["availability"] == "private_deleted_or_not_returned"
    assert calls.count("/youtube/v3/channels") == 3


@pytest.mark.asyncio
async def test_youtube_quota_error_is_explicit_and_api_key_is_not_in_message() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "Quota exceeded",
                    "errors": [{"reason": "quotaExceeded"}],
                }
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://www.googleapis.com/youtube/v3/",
    )
    adapter = YouTubeAdapter(client=client, max_attempts=1)
    try:
        with pytest.raises(RateLimitError, match="quotaExceeded") as captured:
            await adapter.resolve_account(context(api_key="must-not-leak"), "@sports")
    finally:
        await client.aclose()
    assert "must-not-leak" not in str(captured.value)


@pytest.mark.asyncio
async def test_mock_is_deterministic_and_skeletons_fail_explicitly() -> None:
    adapter = MockPlatformAdapter()
    ctx = context(seed="stable", snapshot_index=2)
    first = await adapter.resolve_account(ctx, "creator")
    second = await adapter.resolve_account(ctx, "creator")
    metrics = await adapter.fetch_account_analytics(ctx, first.external_id)
    assert first == second
    assert first.source_kind == "mock"
    assert first.metadata["is_mock"] is True
    assert metrics.metadata["snapshot_index"] == 2

    registry = build_platform_adapter_registry()
    try:
        assert set(registry.keys()) == {
            "bilibili",
            "douyin",
            "mock_platform",
            "tiktok",
            "youtube",
        }
        for key in ("tiktok", "douyin", "bilibili"):
            skeleton = registry.get(key)
            assert skeleton.descriptor.implementation_status == "skeleton"
            with pytest.raises(AdapterNotImplementedError):
                await skeleton.resolve_account(context(), "creator")
    finally:
        for registered in registry.values():
            close = getattr(registered, "aclose", None)
            if close is not None:
                await close()
