import asyncio
import logging
import re
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
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
TIKTOK_API_BASE_URL = "https://open.tiktokapis.com/v2/"
TIKTOK_OAUTH_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105
TIKTOK_PROFILE_URL_PREFIX = "https://www.tiktok.com/@"
TIKTOK_USERNAME_RE = re.compile(r"^@?([A-Za-z0-9._]+)$")


def parse_unix_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        ts = int(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("TikTok returned an invalid unix timestamp") from exc
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


def parse_count(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("TikTok returned an invalid counter value") from exc


def parse_duration_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("TikTok returned an invalid duration") from exc
    if seconds < 0:
        return None
    return seconds


def extract_username(locator: str) -> str:
    value = locator.strip()
    if not value:
        raise AdapterConfigurationError("TikTok username locator is required")
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if "tiktok.com" not in host:
            raise AdapterConfigurationError(
                "TikTok URL must point to tiktok.com"
            )
        path = parsed.path.strip("/")
        if path.startswith("@"):
            username = path.split("/", 1)[0].lstrip("@")
        else:
            username = path.split("/", 1)[0]
        if not username:
            raise AdapterConfigurationError(
                "TikTok URL must contain a username (e.g. tiktok.com/@user)"
            )
        return username
    if value.startswith("@"):
        return value[1:]
    return value


class TikTokAdapter(PlatformAdapter):
    descriptor = AdapterDescriptor(
        key="tiktok",
        name="TikTok Display API",
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
                key="client_key",
                label="TikTok Client Key",
                required=True,
                secret=False,
                description="TikTok 开发者平台应用的 Client Key",
            ),
            AdapterConfigField(
                key="client_secret",
                label="TikTok Client Secret",
                required=True,
                secret=True,
                description="TikTok 开发者平台应用的 Client Secret",
            ),
            AdapterConfigField(
                key="access_token",
                label="TikTok Access Token",
                required=True,
                secret=True,
                description="通过 OAuth 流程获取的 Access Token",
            ),
            AdapterConfigField(
                key="refresh_token",
                label="TikTok Refresh Token",
                required=False,
                secret=True,
                description="用于自动刷新 Access Token 的 Refresh Token",
            ),
        ),
        source_kinds=frozenset({"live"}),
    )

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = TIKTOK_API_BASE_URL,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.5,
        min_request_interval: float = 0.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._owns_client = client is None
        self._max_attempts = max(1, min(max_attempts, 5))
        self._retry_base_seconds = max(0.0, retry_base_seconds)
        self._min_request_interval = max(0.0, min_request_interval)
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._refresh_lock = asyncio.Lock()
        self._last_refreshed_at = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        client_key = config.get("client_key")
        if not isinstance(client_key, str) or not client_key.strip():
            raise AdapterConfigurationError("TikTok client_key is required")
        client_secret = config.get("client_secret")
        if not isinstance(client_secret, str) or not client_secret.strip():
            raise AdapterConfigurationError("TikTok client_secret is required")
        access_token = config.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise AdapterConfigurationError("TikTok access_token is required")

    async def _throttle(self) -> None:
        async with self._request_lock:
            remaining = self._min_request_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def _refresh_access_token(self, config: Mapping[str, Any]) -> dict[str, Any] | None:
        refresh_token = config.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            return None
        client_key = cast(str, config["client_key"])
        client_secret = cast(str, config["client_secret"])

        async with self._refresh_lock:
            now = time.monotonic()
            if now - self._last_refreshed_at < 5.0:
                return None
            self._last_refreshed_at = now

        started = time.perf_counter()
        try:
            response = await self._client.post(
                TIKTOK_OAUTH_TOKEN_URL,
                data={
                    "client_key": client_key,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning(
                "tiktok_token_refresh_transport_error",
                extra={
                    "event": "provider.tiktok.token_refresh",
                    "error": type(exc).__name__,
                },
            )
            return None

        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if not response.is_success:
            logger.warning(
                "tiktok_token_refresh_failed",
                extra={
                    "event": "provider.tiktok.token_refresh",
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None

        new_access_token = payload.get("access_token")
        if not isinstance(new_access_token, str) or not new_access_token.strip():
            return None

        logger.info(
            "tiktok_token_refreshed",
            extra={
                "event": "provider.tiktok.token_refresh",
                "duration_ms": duration_ms,
                "expires_in": payload.get("expires_in"),
            },
        )
        return payload

    async def _request(
        self,
        ctx: AdapterCallContext,
        endpoint: str,
        body: Mapping[str, Any] | None = None,
        *,
        method: str = "POST",
        params: Mapping[str, Any] | None = None,
        _allow_token_refresh: bool = True,
    ) -> dict[str, Any]:
        await self.validate_config(ctx.config)
        access_token = cast(str, ctx.config["access_token"])
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            await self._throttle()
            started = time.perf_counter()
            try:
                response = await self._client.request(
                    method,
                    endpoint,
                    params=params,
                    json=dict(body) if body is not None else None,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = TransientAdapterError(type(exc).__name__)
                response = None
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "tiktok_api_request",
                extra={
                    "event": "provider.tiktok.request",
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

            if not response.is_success:
                error = self._map_http_error(response)
                if (
                    isinstance(error, AuthenticationError)
                    and _allow_token_refresh
                    and attempt == 1
                ):
                    refreshed = await self._refresh_access_token(ctx.config)
                    if refreshed is not None:
                        access_token = cast(str, refreshed["access_token"])
                        logger.info(
                            "tiktok_retry_with_refreshed_token",
                            extra={
                                "event": "provider.tiktok.request",
                                "request_id": ctx.request_id,
                                "endpoint": endpoint,
                            },
                        )
                        continue
                if error.retryable and attempt < self._max_attempts:
                    retry_after = error.retry_after if isinstance(error, RateLimitError) else None
                    delay = retry_after or self._retry_base_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue
                raise error

            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterContractError("TikTok returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise AdapterContractError("TikTok returned a non-object response")

            tiktok_error = payload.get("error")
            if isinstance(tiktok_error, dict):
                error_code = tiktok_error.get("code")
                if error_code not in {None, 0, "0", "ok"}:
                    mapped = self._map_tiktok_error(tiktok_error)
                    if (
                        isinstance(mapped, AuthenticationError)
                        and _allow_token_refresh
                        and attempt == 1
                    ):
                        refreshed = await self._refresh_access_token(ctx.config)
                        if refreshed is not None:
                            access_token = cast(str, refreshed["access_token"])
                            logger.info(
                                "tiktok_retry_with_refreshed_token",
                                extra={
                                    "event": "provider.tiktok.request",
                                    "request_id": ctx.request_id,
                                    "endpoint": endpoint,
                                },
                            )
                            continue
                    if mapped.retryable and attempt < self._max_attempts:
                        retry_after = (
                            mapped.retry_after if isinstance(mapped, RateLimitError) else None
                        )
                        delay = retry_after or self._retry_base_seconds * (2 ** (attempt - 1))
                        await asyncio.sleep(delay)
                        continue
                    raise mapped

            return cast(dict[str, Any], payload)

        raise TransientAdapterError("TikTok request exhausted retry attempts")

    def _map_http_error(self, response: httpx.Response) -> PlatformAdapterError:
        message = f"TikTok API returned HTTP {response.status_code}"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                tiktok_error = payload.get("error")
                if isinstance(tiktok_error, dict):
                    msg = tiktok_error.get("message")
                    if isinstance(msg, str) and msg:
                        message = msg
        except ValueError:
            pass
        if response.status_code == 401:
            return AuthenticationError(message)
        if response.status_code == 403:
            return PermissionDeniedError(message)
        if response.status_code == 429:
            retry_header = response.headers.get("Retry-After")
            retry_after = float(retry_header) if retry_header and retry_header.isdigit() else None
            return RateLimitError(message, retry_after=retry_after)
        if response.status_code in {404, 410}:
            return AdapterNotFoundError(message)
        if response.status_code >= 500:
            return TransientAdapterError(message)
        if response.status_code == 400:
            return AdapterConfigurationError(message)
        return AdapterContractError(message)

    @staticmethod
    def _map_tiktok_error(error: Mapping[str, Any]) -> PlatformAdapterError:
        code = str(error.get("code") or "unknown_error")
        normalized = code.casefold()
        message = str(error.get("message") or f"TikTok API error code={code}")
        if normalized in {"10003", "10004", "10005"} or "scope" in normalized:
            return PermissionDeniedError(message)
        if normalized in {"10001", "10002"} or any(
            marker in normalized for marker in ("token", "auth")
        ):
            return AuthenticationError(message)
        if normalized == "10006" or "rate" in normalized:
            return RateLimitError(message)
        if normalized == "10007" or "not_found" in normalized:
            return AdapterNotFoundError(message)
        if normalized.isdigit() and int(normalized) >= 20_000:
            return TransientAdapterError(message)
        return AdapterContractError(f"{message} (code={code})")

    def _map_account(self, user: Mapping[str, Any], fetched_at: datetime) -> PlatformAccountData:
        username = str(user.get("username") or "")
        display_name = str(user.get("display_name") or username or "unknown")
        if not username:
            raise AdapterContractError("TikTok user info is missing username")
        profile_url = str(user.get("profile_deep_link") or "") or (
            TIKTOK_PROFILE_URL_PREFIX + username
        )
        return PlatformAccountData(
            external_id=username,
            username=username,
            display_name=display_name,
            profile_url=profile_url,
            avatar_url=str(user["avatar_url"]) if user.get("avatar_url") else None,
            description=str(user["bio_description"]) if user.get("bio_description") else None,
            country=None,
            language=None,
            is_verified=(
                user.get("is_verified")
                if isinstance(user.get("is_verified"), bool)
                else None
            ),
            source_kind="live",
            provider=self.key,
            fetched_at=fetched_at,
            metadata={
                "follower_count": parse_count(user.get("follower_count")),
                "following_count": parse_count(user.get("following_count")),
                "likes_count": parse_count(user.get("likes_count")),
                "video_count": parse_count(user.get("video_count")),
                "provider_schema_version": "tiktok-display-api-v2",
            },
        )

    async def _fetch_user_info(
        self, ctx: AdapterCallContext
    ) -> dict[str, Any]:
        fields = [
            "username",
            "display_name",
            "profile_deep_link",
            "avatar_url",
            "bio_description",
            "is_verified",
            "follower_count",
            "following_count",
            "likes_count",
            "video_count",
        ]
        payload = await self._request(
            ctx,
            "user/info/",
            method="GET",
            params={"fields": ",".join(fields)},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AdapterContractError("TikTok user info response missing data object")
        user = data.get("user")
        if not isinstance(user, dict):
            raise AdapterNotFoundError("TikTok user info response missing user object")
        return cast(dict[str, Any], user)

    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        target_username = extract_username(locator)
        user = await self._fetch_user_info(ctx)
        api_username = str(user.get("username") or "")
        if api_username and api_username.lower() == target_username.lower():
            return self._map_account(user, ctx.observed_at)
        raise PermissionDeniedError(
            "TikTok Display API can only resolve the account authorized by the access token"
        )

    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData:
        user = await self._fetch_user_info(ctx)
        api_username = str(user.get("username") or "")
        if api_username and api_username.lower() == external_id.lower():
            return self._map_account(user, ctx.observed_at)
        raise PermissionDeniedError(
            "TikTok Display API returned a different authorized account"
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
        max_count = max(1, min(page_size, 20))
        cursor_int = 0
        if cursor is not None:
            try:
                cursor_int = int(cursor)
            except (TypeError, ValueError) as exc:
                raise AdapterConfigurationError(
                    "TikTok cursor must be a numeric string"
                ) from exc
        fields = [
                "id",
                "title",
                "create_time",
                "duration",
                "cover_image_url",
                "embed_link",
                "like_count",
                "comment_count",
                "share_count",
                "view_count",
            ]
        body: dict[str, Any] = {
            "max_count": max_count,
            "cursor": cursor_int,
        }
        payload = await self._request(
            ctx, "video/list/", body, params={"fields": ",".join(fields)}
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AdapterContractError("TikTok video list response missing data object")

        videos = data.get("videos")
        if not isinstance(videos, list):
            raise AdapterContractError("TikTok video list response missing videos array")

        mapped: list[PlatformContentData] = []
        reached_checkpoint = False
        for video in videos:
            if not isinstance(video, dict):
                continue
            published_at = parse_unix_timestamp(video.get("create_time"))
            if published_after and published_at and published_at <= published_after:
                reached_checkpoint = True
                continue
            mapped.append(self._map_video(video, external_account_id, ctx.observed_at))

        has_more = bool(data.get("has_more", False))
        next_cursor: str | None = None
        if has_more and not reached_checkpoint:
            raw_cursor = data.get("cursor")
            if raw_cursor is not None:
                next_cursor = str(raw_cursor)

        return AdapterPage(
            items=tuple(mapped),
            next_cursor=next_cursor,
            checkpoint={
                "external_account_id": external_account_id,
                "published_after": published_after.isoformat() if published_after else None,
            },
        )

    def _map_video(
        self, item: Mapping[str, Any], account_external_id: str, fetched_at: datetime
    ) -> PlatformContentData:
        video_id = str(item.get("id") or "")
        if not video_id:
            raise AdapterContractError("TikTok video is missing id")
        title = str(item.get("title") or video_id)
        username = account_external_id
        embed_link = item.get("embed_link")
        if isinstance(embed_link, str) and embed_link.strip():
            canonical_url = embed_link
        else:
            canonical_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
        return PlatformContentData(
            external_id=video_id,
            account_external_id=account_external_id,
            content_type="video",
            title=title,
            description=None,
            published_at=parse_unix_timestamp(item.get("create_time")),
            duration_seconds=parse_duration_seconds(item.get("duration")),
            canonical_url=canonical_url,
            cover_url=str(item["cover_image_url"]) if item.get("cover_image_url") else None,
            language=None,
            status="published",
            source_kind="live",
            provider=self.key,
            fetched_at=fetched_at,
            metadata={
                "like_count": parse_count(item.get("like_count")),
                "comment_count": parse_count(item.get("comment_count")),
                "share_count": parse_count(item.get("share_count")),
                "view_count": parse_count(item.get("view_count")),
                "provider_schema_version": "tiktok-display-api-v2",
            },
        )

    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData:
        fields = [
            "id",
            "title",
            "create_time",
            "duration",
            "cover_image_url",
            "like_count",
            "comment_count",
            "share_count",
            "view_count",
        ]
        payload = await self._request(
            ctx,
            "video/query/",
            {"filters": {"video_ids": [external_id]}},
            params={"fields": ",".join(fields)},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AdapterContractError("TikTok video query response missing data object")
        videos = data.get("videos")
        if not isinstance(videos, list) or not videos:
            raise AdapterNotFoundError("TikTok video was not found")
        first = videos[0]
        if not isinstance(first, dict):
            raise AdapterContractError("TikTok video query returned an invalid video object")
        return self._map_video(first, "unknown", ctx.observed_at)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        try:
            user = await self._fetch_user_info(ctx)
            api_username = str(user.get("username") or "")
            if api_username and api_username.lower() == external_id.lower():
                return PlatformMetricsData(
                    external_id=external_id,
                    captured_at=ctx.observed_at,
                    metrics={
                        "follower_count": parse_count(user.get("follower_count")),
                        "following_count": parse_count(user.get("following_count")),
                        "total_like_count": parse_count(user.get("likes_count")),
                        "total_view_count": None,
                        "video_count": parse_count(user.get("video_count")),
                        "engagement_rate": None,
                    },
                    source_kind="live",
                    provider=self.key,
                    fetched_at=ctx.observed_at,
                    unavailable_metrics=("total_view_count", "engagement_rate"),
                    metadata={
                        "scope": "tiktok_display_api_v2",
                        "is_verified": user.get("is_verified"),
                        "provider_schema_version": "tiktok-display-api-v2",
                    },
                )
        except (
            AdapterNotFoundError,
            AuthenticationError,
            PermissionDeniedError,
            TransientAdapterError,
        ):
            pass
        # Cannot fetch analytics for accounts other than the token owner.
        return PlatformMetricsData(
            external_id=external_id,
            captured_at=ctx.observed_at,
            metrics={},
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            unavailable_metrics=("all",),
            metadata={
                "scope": "tiktok_display_api_v2",
                "availability": "token_owner_only",
                "provider_schema_version": "tiktok-display-api-v2",
            },
        )

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        metrics: list[PlatformMetricsData] = []
        for video_id in external_ids:
            if not video_id:
                continue
            fields = [
                "id",
                "like_count",
                "comment_count",
                "share_count",
                "view_count",
            ]
            try:
                payload = await self._request(
                    ctx,
                    "video/query/",
                    {"filters": {"video_ids": [video_id]}},
                    params={"fields": ",".join(fields)},
                )
            except AdapterNotFoundError:
                metrics.append(
                    PlatformMetricsData(
                        external_id=video_id,
                        captured_at=ctx.observed_at,
                        metrics={},
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=("all",),
                        metadata={"availability": "not_found_or_deleted"},
                    )
                )
                continue

            data = payload.get("data")
            videos = data.get("videos") if isinstance(data, dict) else None
            if not isinstance(videos, list) or not videos:
                metrics.append(
                    PlatformMetricsData(
                        external_id=video_id,
                        captured_at=ctx.observed_at,
                        metrics={},
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=("all",),
                        metadata={"availability": "not_returned"},
                    )
                )
                continue

            video = videos[0]
            if not isinstance(video, dict):
                continue

            metrics.append(
                PlatformMetricsData(
                    external_id=str(video.get("id") or video_id),
                    captured_at=ctx.observed_at,
                    metrics={
                        "view_count": parse_count(video.get("view_count")),
                        "like_count": parse_count(video.get("like_count")),
                        "comment_count": parse_count(video.get("comment_count")),
                        "share_count": parse_count(video.get("share_count")),
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
                        "scope": "tiktok_display_api_v2",
                        "provider_schema_version": "tiktok-display-api-v2",
                    },
                )
            )
        return tuple(metrics)

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        try:
            await self._fetch_user_info(ctx)
        except Exception as exc:
            if isinstance(exc, (AdapterConfigurationError, AuthenticationError, RateLimitError)):
                return AdapterHealth(
                    status="unavailable",
                    checked_at=ctx.observed_at,
                    detail=f"{getattr(exc, 'code', 'error')}: {exc}",
                )
            raise
        return AdapterHealth(status="ok", checked_at=ctx.observed_at)
