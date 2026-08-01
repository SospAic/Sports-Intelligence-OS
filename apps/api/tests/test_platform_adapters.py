import json
from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.platforms.base import (
    AdapterCallContext,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from app.adapters.platforms.douyin import DouyinAdapter
from app.adapters.platforms.registry import build_platform_adapter_registry
from app.adapters.platforms.tiktok import TikTokAdapter
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
async def test_tiktok_display_api_uses_official_methods_query_fields_and_body_shape() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        assert request.url.params.get("fields")
        if request.url.path.endswith("/user/info/"):
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "username": "sports_owner",
                            "display_name": "Sports Owner",
                            "video_count": 1,
                        }
                    },
                    "error": {"code": "ok", "message": ""},
                },
            )
        if request.url.path.endswith("/video/list/"):
            assert request.method == "POST"
            assert "fields" not in body and "filters" not in body
            return httpx.Response(
                200,
                json={
                    "data": {
                        "videos": [
                            {
                                "id": "video-1",
                                "title": "Match recap",
                                "create_time": 1784973600,
                                "cover_image_url": "https://cdn.example/cover.jpg",
                            }
                        ],
                        "has_more": False,
                    },
                    "error": {"code": "ok", "message": ""},
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.tiktokapis.com/v2/",
    )
    adapter = TikTokAdapter(client=client, max_attempts=1)
    ctx = context(client_key="key", client_secret="secret", access_token="token")
    try:
        account = await adapter.resolve_account(ctx, "@sports_owner")
        page = await adapter.list_contents(
            ctx,
            account.external_id,
            published_after=None,
            cursor=None,
            page_size=20,
        )
    finally:
        await client.aclose()

    assert account.metadata["provider_schema_version"] == "tiktok-display-api-v2"
    assert page.items[0].cover_url == "https://cdn.example/cover.jpg"
    assert [call[:2] for call in calls] == [
        ("GET", "/v2/user/info/"),
        ("POST", "/v2/video/list/"),
    ]


def test_tiktok_string_scope_error_maps_without_integer_conversion() -> None:
    error = TikTokAdapter._map_tiktok_error(
        {"code": "scope_not_authorized", "message": "scope missing"}
    )
    assert isinstance(error, PermissionDeniedError)


@pytest.mark.asyncio
async def test_registry_excludes_mock_adapters_and_all_are_implemented() -> None:
    """The production adapter registry must never contain a 'mock' adapter, and
    every registered adapter must be a real, implemented adapter (not a skeleton
    that would falsify monitoring state)."""
    registry = build_platform_adapter_registry()
    try:
        assert "mock_platform" not in registry.keys()
        assert all(not key.startswith("mock") for key in registry.keys())
        assert all(
            registry.get(key).descriptor.implementation_status == "implemented"
            for key in registry.keys()
        )
    finally:
        for registered in registry.values():
            close = getattr(registered, "aclose", None)
            if close is not None:
                await close()


@pytest.mark.asyncio
async def test_douyin_resolve_account_and_analytics() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/api/douyin/v1/user/info/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "error_code": 0,
                        "open_id": "test-open-id-123",
                        "nickname": "体育达人",
                        "avatar": "https://p3.douyinpic.com/avatar/test.jpg",
                        "country": "中国",
                        "province": "北京",
                        "city": "北京",
                        "e_account_info": {"is_verified": True},
                    }
                },
            )
        if path.endswith("/api/douyin/v1/user/fan_data/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "error_code": 0,
                        "total_fans": 50000,
                        "all_fans_num": 50000,
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.douyin.com",
    )
    adapter = DouyinAdapter(client=client, max_attempts=1)
    ctx = context(
        client_key="test-key",
        client_secret="test-secret",
        access_token="test-token",
    )
    try:
        account = await adapter.resolve_account(
            ctx, "https://www.douyin.com/user/MS4wLjABAAAAtest123"
        )
        analytics = await adapter.fetch_account_analytics(ctx, account.external_id)
    finally:
        await client.aclose()

    assert account.source_kind == "live"
    assert account.provider == "douyin"
    assert account.external_id == "test-open-id-123"
    assert account.display_name == "体育达人"
    assert account.is_verified is True
    assert account.country == "中国"
    assert account.profile_url == "https://www.douyin.com/user/MS4wLjABAAAAtest123"
    assert analytics.metrics["follower_count"] == 50000
    assert "following_count" in analytics.unavailable_metrics


@pytest.mark.asyncio
async def test_douyin_list_contents_pagination_and_checkpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/douyin/v1/video/video_list/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "error_code": 0,
                        "list": [
                            {
                                "item_id": "video-001",
                                "title": "精彩进球集锦",
                                "create_time": 1753430400,
                                "cover": "https://p3.douyinpic.com/cover/001.jpg",
                                "video_status": "published",
                                "share_url": "https://www.douyin.com/video/001",
                                "statistics": {
                                    "play_count": 120000,
                                    "digg_count": 8000,
                                    "comment_count": 500,
                                    "forward_count": 300,
                                    "download_count": 100,
                                },
                            },
                            {
                                "item_id": "video-002",
                                "title": "篮球训练日常",
                                "create_time": 1753344000,
                                "cover": "https://p3.douyinpic.com/cover/002.jpg",
                                "video_status": "published",
                                "share_url": "https://www.douyin.com/video/002",
                                "statistics": {
                                    "play_count": 50000,
                                    "digg_count": 3000,
                                    "comment_count": 200,
                                    "forward_count": 100,
                                    "download_count": 50,
                                },
                            },
                        ],
                        "has_more": True,
                        "cursor": 2,
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.douyin.com",
    )
    adapter = DouyinAdapter(client=client, max_attempts=1)
    ctx = context(
        client_key="test-key",
        client_secret="test-secret",
        access_token="test-token",
    )
    try:
        page = await adapter.list_contents(
            ctx,
            "test-open-id-123",
            published_after=None,
            cursor=None,
            page_size=20,
        )
    finally:
        await client.aclose()

    assert len(page.items) == 2
    assert page.next_cursor == "2"
    assert page.items[0].external_id == "video-001"
    assert page.items[0].title == "精彩进球集锦"
    assert page.items[0].canonical_url == "https://www.douyin.com/video/001"
    assert page.items[0].published_at is not None
    assert page.items[0].source_kind == "live"
    assert page.items[0].provider == "douyin"
    assert page.items[1].external_id == "video-002"


@pytest.mark.asyncio
async def test_douyin_content_analytics_maps_metrics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/douyin/v1/video/video_data/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "error_code": 0,
                        "item_id": "video-001",
                        "title": "精彩进球",
                        "create_time": 1753430400,
                        "cover": "https://p3.douyinpic.com/cover/001.jpg",
                        "video_status": "published",
                        "share_url": "https://www.douyin.com/video/001",
                        "statistics": {
                            "play_count": 200000,
                            "digg_count": 15000,
                            "comment_count": 1200,
                            "forward_count": 800,
                            "download_count": 350,
                        },
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.douyin.com",
    )
    adapter = DouyinAdapter(client=client, max_attempts=1)
    ctx = context(
        client_key="test-key",
        client_secret="test-secret",
        access_token="test-token",
    )
    try:
        results = await adapter.fetch_content_analytics(ctx, ["video-001"])
    finally:
        await client.aclose()

    assert len(results) == 1
    m = results[0]
    assert m.external_id == "video-001"
    assert m.metrics["view_count"] == 200000
    assert m.metrics["like_count"] == 15000
    assert m.metrics["comment_count"] == 1200
    assert m.metrics["share_count"] == 800
    assert m.metrics["favorite_count"] is None
    assert "favorite_count" in m.unavailable_metrics
    assert "revenue" in m.unavailable_metrics
    assert m.metadata["download_count"] == 350


@pytest.mark.asyncio
async def test_douyin_auth_error_mapping() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "error_code": 10001,
                    "description": "access_token is invalid",
                }
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.douyin.com",
    )
    adapter = DouyinAdapter(client=client, max_attempts=1)
    ctx = context(
        client_key="test-key",
        client_secret="test-secret",
        access_token="bad-token",
    )
    try:
        with pytest.raises(AuthenticationError, match="10001"):
            await adapter.resolve_account(ctx, "test-open-id")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_douyin_rate_limit_error_mapping() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "error_code": 10005,
                    "description": "rate limit exceeded",
                }
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://open.douyin.com",
    )
    adapter = DouyinAdapter(client=client, max_attempts=1)
    ctx = context(
        client_key="test-key",
        client_secret="test-secret",
        access_token="test-token",
    )
    try:
        with pytest.raises(RateLimitError, match="10005"):
            await adapter.resolve_account(ctx, "test-open-id")
    finally:
        await client.aclose()
