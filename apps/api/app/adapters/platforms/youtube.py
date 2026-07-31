import asyncio
import logging
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterConfigField,
    AdapterConfigurationError,
    AdapterContractError,
    AdapterDescriptor,
    AdapterHealth,
    AdapterNotFoundError,
    AdapterPage,
    AuthenticationError,
    PermissionDeniedError,
    PlatformAccountData,
    PlatformAdapter,
    PlatformAdapterError,
    PlatformContentData,
    PlatformMetricsData,
    RateLimitError,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3/"
YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v="
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/"
ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?$"
)


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdapterContractError("YouTube returned an invalid datetime") from exc


def parse_duration(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    match = ISO_DURATION.fullmatch(value)
    if match is None:
        raise AdapterContractError("YouTube returned an unsupported ISO 8601 duration")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


def parse_count(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("YouTube returned an invalid statistics counter") from exc


def best_thumbnail(thumbnails: object) -> str | None:
    if not isinstance(thumbnails, dict):
        return None
    candidates = [
        value
        for value in thumbnails.values()
        if isinstance(value, dict) and isinstance(value.get("url"), str)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda item: int(item.get("width", 0) or 0))
    return cast(str, best["url"])


class YouTubeAdapter(PlatformAdapter):
    descriptor = AdapterDescriptor(
        key="youtube",
        name="YouTube Data API",
        implementation_status="implemented",
        capabilities={
            AdapterCapability.PUBLIC_PROFILE: True,
            AdapterCapability.ACCOUNT_ANALYTICS: True,
            AdapterCapability.CONTENT_LIST: True,
            AdapterCapability.CONTENT_ANALYTICS: True,
            AdapterCapability.TRAFFIC_SOURCES: False,
            AdapterCapability.RETENTION: False,
            AdapterCapability.REVENUE: False,
            AdapterCapability.COMMENTS: False,
            AdapterCapability.SEARCH_TERMS: False,
        },
        config_fields=(
            AdapterConfigField(
                key="api_key",
                label="YouTube Data API Key",
                required=True,
                secret=True,
                description="Google Cloud 中启用 YouTube Data API v3 后创建的 API Key",
            ),
        ),
        source_kinds=frozenset({"live"}),
    )

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = YOUTUBE_API_BASE_URL,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        min_request_interval: float = 0.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json"},
        )
        self._owns_client = client is None
        self._max_attempts = max(1, min(max_attempts, 5))
        self._retry_base_seconds = max(0.0, retry_base_seconds)
        self._min_request_interval = max(0.0, min_request_interval)
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        api_key = config.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise AdapterConfigurationError("YouTube api_key is required")

    async def _throttle(self) -> None:
        async with self._request_lock:
            remaining = self._min_request_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def _request(
        self, ctx: AdapterCallContext, endpoint: str, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        await self.validate_config(ctx.config)
        request_params = {**params, "key": cast(str, ctx.config["api_key"])}
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            await self._throttle()
            started = time.perf_counter()
            try:
                response = await self._client.get(endpoint, params=request_params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = TransientAdapterError(type(exc).__name__)
                response = None
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "youtube_api_request",
                extra={
                    "event": "provider.youtube.request",
                    "request_id": ctx.request_id,
                    "endpoint": endpoint,
                    "attempt": attempt,
                    "status_code": response.status_code if response is not None else None,
                    "duration_ms": duration_ms,
                },
            )
            if response is None:
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_base_seconds * (2 ** (attempt - 1)))
                    continue
                assert last_error is not None
                raise last_error

            if response.is_success:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise AdapterContractError("YouTube returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise AdapterContractError("YouTube returned a non-object response")
                return cast(dict[str, Any], payload)

            error = self._map_error(response)
            if error.retryable and attempt < self._max_attempts:
                retry_after = error.retry_after if isinstance(error, RateLimitError) else None
                delay = retry_after or self._retry_base_seconds * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
                continue
            raise error
        raise TransientAdapterError("YouTube request exhausted retry attempts")

    def _map_error(self, response: httpx.Response) -> PlatformAdapterError:
        reason = "unknown"
        message = f"YouTube API returned HTTP {response.status_code}"
        try:
            payload = response.json()
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(error, dict):
                message = str(error.get("message") or message)
                entries = error.get("errors")
                if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                    reason = str(entries[0].get("reason") or reason)
        except ValueError:
            pass
        safe_message = f"{message} (reason={reason})"
        if response.status_code == 401:
            return AuthenticationError(safe_message)
        if response.status_code == 403 and reason in {
            "quotaExceeded",
            "dailyLimitExceeded",
            "rateLimitExceeded",
            "userRateLimitExceeded",
        }:
            retry_header = response.headers.get("Retry-After")
            retry_after = float(retry_header) if retry_header and retry_header.isdigit() else None
            return RateLimitError(safe_message, retry_after=retry_after)
        if response.status_code == 429:
            retry_header = response.headers.get("Retry-After")
            retry_after = float(retry_header) if retry_header and retry_header.isdigit() else None
            return RateLimitError(safe_message, retry_after=retry_after)
        if response.status_code == 403:
            return PermissionDeniedError(safe_message)
        if response.status_code in {404, 410}:
            return AdapterNotFoundError(safe_message)
        if response.status_code >= 500:
            return TransientAdapterError(safe_message)
        if response.status_code == 400:
            return AdapterConfigurationError(safe_message)
        return AdapterContractError(safe_message)

    def _channel_locator_params(self, locator: str) -> dict[str, str]:
        value = locator.strip()
        if not value:
            raise AdapterConfigurationError("YouTube channel locator is required")
        if value.startswith("http://") or value.startswith("https://"):
            path = urlparse(value).path.strip("/")
            if path.startswith("channel/"):
                return {"id": path.split("/", 1)[1]}
            if path.startswith("@"):
                return {"forHandle": path.split("/", 1)[0]}
            raise AdapterConfigurationError("YouTube URL must use /channel/{id} or /@handle")
        if value.startswith("UC") and len(value) >= 20:
            return {"id": value}
        return {"forHandle": value}

    async def _channel_item(
        self, ctx: AdapterCallContext, params: Mapping[str, str]
    ) -> dict[str, Any]:
        payload = await self._request(
            ctx,
            "channels",
            {"part": "snippet,statistics,contentDetails,status", **params},
        )
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise AdapterNotFoundError("YouTube channel was not found")
        if not isinstance(items[0], dict):
            raise AdapterContractError("YouTube channel item has an invalid shape")
        return cast(dict[str, Any], items[0])

    def _map_account(self, item: Mapping[str, Any], fetched_at: datetime) -> PlatformAccountData:
        channel_id = str(item.get("id") or "")
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
        related = details.get("relatedPlaylists") if isinstance(details, dict) else {}
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if not channel_id or not isinstance(snippet, dict):
            raise AdapterContractError("YouTube channel is missing id or snippet")
        return PlatformAccountData(
            external_id=channel_id,
            username=str(snippet.get("customUrl")) if snippet.get("customUrl") else None,
            display_name=str(snippet.get("title") or channel_id),
            profile_url=YOUTUBE_CHANNEL_URL + channel_id,
            avatar_url=best_thumbnail(snippet.get("thumbnails")),
            description=str(snippet.get("description")) if snippet.get("description") else None,
            country=str(snippet.get("country")) if snippet.get("country") else None,
            language=(
                str(snippet.get("defaultLanguage")) if snippet.get("defaultLanguage") else None
            ),
            is_verified=None,
            source_kind="live",
            provider=self.key,
            fetched_at=fetched_at,
            metadata={
                "uploads_playlist_id": (
                    related.get("uploads") if isinstance(related, dict) else None
                ),
                "published_at": snippet.get("publishedAt"),
                "hidden_subscriber_count": (
                    statistics.get("hiddenSubscriberCount")
                    if isinstance(statistics, dict)
                    else None
                ),
                "privacy_status": status.get("privacyStatus") if isinstance(status, dict) else None,
                "provider_schema_version": "youtube-data-api-v3",
            },
        )

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        item = await self._channel_item(ctx, self._channel_locator_params(locator))
        return self._map_account(item, ctx.observed_at)

    async def fetch_account(self, ctx: AdapterCallContext, external_id: str) -> PlatformAccountData:
        item = await self._channel_item(ctx, {"id": external_id})
        return self._map_account(item, ctx.observed_at)

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        channel = await self._channel_item(ctx, {"id": external_account_id})
        details = channel.get("contentDetails")
        related = details.get("relatedPlaylists") if isinstance(details, dict) else None
        uploads_id = related.get("uploads") if isinstance(related, dict) else None
        if not isinstance(uploads_id, str) or not uploads_id:
            raise AdapterContractError("YouTube channel has no uploads playlist")
        params: dict[str, Any] = {
            "part": "snippet,contentDetails,status",
            "playlistId": uploads_id,
            "maxResults": max(1, min(page_size, 50)),
        }
        if cursor:
            params["pageToken"] = cursor
        playlist_payload = await self._request(ctx, "playlistItems", params)
        playlist_items = playlist_payload.get("items")
        if not isinstance(playlist_items, list):
            raise AdapterContractError("YouTube playlist response has no items array")
        video_ids = [
            str(item.get("contentDetails", {}).get("videoId"))
            for item in playlist_items
            if isinstance(item, dict)
            and isinstance(item.get("contentDetails"), dict)
            and item.get("contentDetails", {}).get("videoId")
        ]
        video_map: dict[str, Mapping[str, Any]] = {}
        if video_ids:
            video_payload = await self._request(
                ctx,
                "videos",
                {
                    "part": "snippet,contentDetails,status,statistics",
                    "id": ",".join(video_ids),
                },
            )
            video_items = video_payload.get("items")
            if not isinstance(video_items, list):
                raise AdapterContractError("YouTube videos response has no items array")
            video_map = {
                str(item["id"]): item
                for item in video_items
                if isinstance(item, dict) and item.get("id")
            }

        mapped: list[PlatformContentData] = []
        reached_checkpoint = False
        for playlist_item in playlist_items:
            if not isinstance(playlist_item, dict):
                continue
            content_details = playlist_item.get("contentDetails")
            snippet = playlist_item.get("snippet")
            if not isinstance(content_details, dict) or not isinstance(snippet, dict):
                continue
            video_id = str(content_details.get("videoId") or "")
            if not video_id:
                continue
            published_at = parse_datetime(
                content_details.get("videoPublishedAt") or snippet.get("publishedAt")
            )
            if published_after and published_at and published_at <= published_after:
                reached_checkpoint = True
                continue
            video = video_map.get(video_id)
            if video is None:
                mapped.append(
                    self._map_unavailable_video(video_id, external_account_id, snippet, ctx)
                )
            else:
                mapped.append(self._map_video(video, external_account_id, ctx.observed_at))
        next_cursor = playlist_payload.get("nextPageToken")
        if reached_checkpoint or not isinstance(next_cursor, str):
            next_cursor = None
        return AdapterPage(
            items=tuple(mapped),
            next_cursor=next_cursor,
            checkpoint={
                "uploads_playlist_id": uploads_id,
                "published_after": published_after.isoformat() if published_after else None,
            },
        )

    def _map_unavailable_video(
        self,
        video_id: str,
        account_id: str,
        snippet: Mapping[str, Any],
        ctx: AdapterCallContext,
    ) -> PlatformContentData:
        title = str(snippet.get("title") or "Unavailable YouTube video")
        return PlatformContentData(
            external_id=video_id,
            account_external_id=account_id,
            content_type="video",
            title=title,
            description=None,
            published_at=parse_datetime(snippet.get("publishedAt")),
            duration_seconds=None,
            canonical_url=YOUTUBE_VIDEO_URL + video_id,
            cover_url=best_thumbnail(snippet.get("thumbnails")),
            language=None,
            status="unavailable",
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={
                "availability": "private_deleted_or_not_returned",
                "statistics_available": False,
                "provider_schema_version": "youtube-data-api-v3",
            },
        )

    def _map_video(
        self, item: Mapping[str, Any], account_id: str, fetched_at: datetime
    ) -> PlatformContentData:
        video_id = str(item.get("id") or "")
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if not video_id or not isinstance(snippet, dict):
            raise AdapterContractError("YouTube video is missing id or snippet")
        return PlatformContentData(
            external_id=video_id,
            account_external_id=account_id,
            content_type="video",
            title=str(snippet.get("title") or video_id),
            description=str(snippet.get("description")) if snippet.get("description") else None,
            published_at=parse_datetime(snippet.get("publishedAt")),
            duration_seconds=(
                parse_duration(details.get("duration")) if isinstance(details, dict) else None
            ),
            canonical_url=YOUTUBE_VIDEO_URL + video_id,
            cover_url=best_thumbnail(snippet.get("thumbnails")),
            language=(
                str(snippet.get("defaultLanguage")) if snippet.get("defaultLanguage") else None
            ),
            status=(str(status.get("privacyStatus")) if isinstance(status, dict) else "published"),
            source_kind="live",
            provider=self.key,
            fetched_at=fetched_at,
            metadata={
                "category_id": snippet.get("categoryId"),
                "tags": snippet.get("tags", []),
                "live_broadcast_content": snippet.get("liveBroadcastContent"),
                "licensed_content": (
                    details.get("licensedContent") if isinstance(details, dict) else None
                ),
                "provider_schema_version": "youtube-data-api-v3",
            },
        )

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        payload = await self._request(
            ctx,
            "videos",
            {"part": "snippet,contentDetails,status,statistics", "id": external_id},
        )
        items = payload.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise AdapterNotFoundError("YouTube video was not found or is not public")
        item = cast(dict[str, Any], items[0])
        snippet = item.get("snippet")
        account_id = (
            str(snippet.get("channelId")) if isinstance(snippet, dict) else "unknown-channel"
        )
        return self._map_video(item, account_id, ctx.observed_at)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        item = await self._channel_item(ctx, {"id": external_id})
        statistics = item.get("statistics")
        if not isinstance(statistics, dict):
            raise AdapterContractError("YouTube channel statistics are unavailable")
        subscribers = (
            None
            if statistics.get("hiddenSubscriberCount") is True
            else parse_count(statistics.get("subscriberCount"))
        )
        return PlatformMetricsData(
            external_id=external_id,
            captured_at=ctx.observed_at,
            metrics={
                "follower_count": subscribers,
                "following_count": None,
                "total_like_count": None,
                "total_view_count": parse_count(statistics.get("viewCount")),
                "video_count": parse_count(statistics.get("videoCount")),
                "engagement_rate": None,
            },
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            unavailable_metrics=("following_count", "total_like_count", "engagement_rate"),
            metadata={
                "scope": "public_youtube_data_api",
                "private_youtube_analytics_api_used": False,
                "hidden_subscriber_count": statistics.get("hiddenSubscriberCount"),
            },
        )

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        metrics: list[PlatformMetricsData] = []
        for start in range(0, len(external_ids), 50):
            batch = [item for item in external_ids[start : start + 50] if item]
            if not batch:
                continue
            payload = await self._request(
                ctx,
                "videos",
                {"part": "statistics", "id": ",".join(batch)},
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise AdapterContractError("YouTube video statistics response is invalid")
            returned: set[str] = set()
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                video_id = str(item["id"])
                returned.add(video_id)
                statistics = item.get("statistics")
                if not isinstance(statistics, dict):
                    statistics = {}
                metrics.append(
                    PlatformMetricsData(
                        external_id=video_id,
                        captured_at=ctx.observed_at,
                        metrics={
                            "view_count": parse_count(statistics.get("viewCount")),
                            "like_count": parse_count(statistics.get("likeCount")),
                            "comment_count": parse_count(statistics.get("commentCount")),
                            "share_count": None,
                            "favorite_count": None,
                            "follower_gain": None,
                            "average_watch_time": None,
                            "completion_rate": None,
                            "search_traffic_rate": None,
                            "recommendation_traffic_rate": None,
                            "profile_traffic_rate": None,
                            "revenue": None,
                            "rpm": None,
                        },
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=(
                            "share_count",
                            "favorite_count",
                            "follower_gain",
                            "average_watch_time",
                            "completion_rate",
                            "search_traffic_rate",
                            "recommendation_traffic_rate",
                            "profile_traffic_rate",
                            "revenue",
                            "rpm",
                        ),
                        metadata={
                            "scope": "public_youtube_data_api",
                            "private_youtube_analytics_api_used": False,
                        },
                    )
                )
            for missing_id in set(batch) - returned:
                metrics.append(
                    PlatformMetricsData(
                        external_id=missing_id,
                        captured_at=ctx.observed_at,
                        metrics={},
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=("all",),
                        metadata={"availability": "private_deleted_or_not_returned"},
                    )
                )
        return tuple(metrics)

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        try:
            await self._request(ctx, "i18nLanguages", {"part": "snippet", "hl": "en"})
        except Exception as exc:
            if isinstance(exc, (AdapterConfigurationError, AuthenticationError, RateLimitError)):
                return AdapterHealth(
                    status="unavailable",
                    checked_at=ctx.observed_at,
                    detail=f"{getattr(exc, 'code', 'error')}: {exc}",
                )
            raise
        return AdapterHealth(status="ok", checked_at=ctx.observed_at)
