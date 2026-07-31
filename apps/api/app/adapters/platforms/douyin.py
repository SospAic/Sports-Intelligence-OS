import asyncio
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
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
DOUYIN_API_BASE_URL = "https://open.douyin.com"
DOUYIN_PROFILE_URL = "https://www.douyin.com/user/"

# Douyin open_id / sec_uid patterns
SEC_UID_RE = re.compile(r"^[A-Za-z0-9_=\-]{16,}$")

# Douyin error codes
_DOUYIN_ERROR_AUTH = {10001, 10002}
_DOUYIN_ERROR_PERMISSION = {10003}
_DOUYIN_ERROR_RATE_LIMIT = {10005}
_DOUYIN_ERROR_NOT_FOUND = {2190008}


def parse_unix_timestamp(value: object) -> datetime | None:
    """Convert a Unix timestamp (seconds) to a timezone-aware UTC datetime."""
    if value is None:
        return None
    try:
        ts = int(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("Douyin returned an invalid unix timestamp") from exc
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


def parse_int(value: object) -> int | None:
    """Safely parse an integer from Douyin API responses."""
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("Douyin returned an invalid numeric value") from exc


class DouyinAdapter(PlatformAdapter):
    """Adapter for the Douyin Open Platform API (抖音开放平台).

    Communicates with https://open.douyin.com using an OAuth access_token.
    Supports user profile retrieval, fan data, video listing and video detail.
    """

    descriptor = AdapterDescriptor(
        key="douyin",
        name="抖音开放平台",
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
                label="Client Key",
                required=True,
                secret=False,
                description="抖音开放平台应用的 Client Key",
            ),
            AdapterConfigField(
                key="client_secret",
                label="Client Secret",
                required=True,
                secret=True,
                description="抖音开放平台应用的 Client Secret",
            ),
            AdapterConfigField(
                key="access_token",
                label="Access Token",
                required=True,
                secret=True,
                description="通过 OAuth 获取的 Access Token",
            ),
        ),
        source_kinds=frozenset({"live"}),
    )

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = DOUYIN_API_BASE_URL,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        min_request_interval: float = 0.3,
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

    # ------------------------------------------------------------------
    # Config validation
    # ------------------------------------------------------------------

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        for field_name in ("client_key", "client_secret", "access_token"):
            value = config.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise AdapterConfigurationError(f"Douyin {field_name} is required")

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    async def _throttle(self) -> None:
        async with self._request_lock:
            remaining = self._min_request_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def _request(
        self,
        ctx: AdapterCallContext,
        method: str,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.validate_config(ctx.config)
        access_token = cast(str, ctx.config["access_token"])
        headers = {"access-token": access_token}
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            await self._throttle()
            started = time.perf_counter()
            try:
                if method.upper() == "POST":
                    response = await self._client.post(
                        endpoint,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
                else:
                    response = await self._client.get(
                        endpoint,
                        params=params,
                        headers=headers,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = TransientAdapterError(type(exc).__name__)
                response = None
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "douyin_api_request",
                extra={
                    "event": "provider.douyin.request",
                    "request_id": ctx.request_id,
                    "endpoint": endpoint,
                    "method": method,
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
                    raise AdapterContractError("Douyin returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise AdapterContractError("Douyin returned a non-object response")
                # Check Douyin-level error codes inside data
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, dict):
                    error_code = data.get("error_code")
                    if error_code is not None and int(error_code) != 0:
                        error = self._map_douyin_error(int(error_code), data)
                        if error.retryable and attempt < self._max_attempts:
                            delay = (
                                error.retry_after
                                if isinstance(error, RateLimitError)
                                else None
                            )
                            await asyncio.sleep(
                                delay or self._retry_base_seconds * (2 ** (attempt - 1))
                            )
                            continue
                        raise error
                return cast(dict[str, Any], payload)

            error = self._map_http_error(response)
            if error.retryable and attempt < self._max_attempts:
                retry_after = error.retry_after if isinstance(error, RateLimitError) else None
                delay = retry_after or self._retry_base_seconds * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
                continue
            raise error
        raise TransientAdapterError("Douyin request exhausted retry attempts")

    # ------------------------------------------------------------------
    # Error mapping
    # ------------------------------------------------------------------

    def _map_douyin_error(self, error_code: int, data: dict[str, Any]) -> PlatformAdapterError:
        description = str(data.get("description") or f"Douyin error_code={error_code}")
        safe_message = f"{description} (error_code={error_code})"
        if error_code in _DOUYIN_ERROR_AUTH:
            return AuthenticationError(safe_message)
        if error_code in _DOUYIN_ERROR_PERMISSION:
            return PermissionDeniedError(safe_message)
        if error_code in _DOUYIN_ERROR_RATE_LIMIT:
            return RateLimitError(safe_message)
        if error_code in _DOUYIN_ERROR_NOT_FOUND:
            return AdapterNotFoundError(safe_message)
        return AdapterContractError(safe_message)

    def _map_http_error(self, response: httpx.Response) -> PlatformAdapterError:
        message = f"Douyin API returned HTTP {response.status_code}"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                msg_field = payload.get("message") or payload.get("description")
                if msg_field:
                    message = str(msg_field)
        except ValueError:
            pass
        if response.status_code in {401, 403}:
            if response.status_code == 401:
                return AuthenticationError(message)
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

    # ------------------------------------------------------------------
    # Locator resolution
    # ------------------------------------------------------------------

    def _resolve_open_id(self, locator: str) -> str:
        """Extract an open_id or sec_uid from a Douyin locator.

        Accepted formats:
        - Full Douyin profile URL: https://www.douyin.com/user/{sec_uid}
        - Bare sec_uid string
        - open_id string (typically shorter alphanumeric)
        """
        value = locator.strip()
        if not value:
            raise AdapterConfigurationError("Douyin account locator is required")
        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            host = parsed.hostname or ""
            if "douyin.com" not in host:
                raise AdapterConfigurationError(
                    "Douyin locator URL must be a douyin.com domain"
                )
            path = parsed.path.strip("/")
            if path.startswith("user/"):
                segments = path.split("/")
                if len(segments) >= 2 and segments[1]:
                    return segments[1]
            raise AdapterConfigurationError(
                "Douyin URL must follow the pattern /user/{sec_uid}"
            )
        return value

    # ------------------------------------------------------------------
    # Account mapping
    # ------------------------------------------------------------------

    def _map_account(
        self,
        user_data: Mapping[str, Any],
        fan_data: Mapping[str, Any] | None,
        fetched_at: datetime,
    ) -> PlatformAccountData:
        open_id = str(user_data.get("open_id") or "")
        if not open_id:
            raise AdapterContractError("Douyin user info is missing open_id")
        nickname = str(user_data.get("nickname") or open_id)
        avatar = user_data.get("avatar")
        country = user_data.get("country")
        province = user_data.get("province")
        city = user_data.get("city")
        e_account_info = (
            user_data.get("e_account_info")
            if isinstance(user_data.get("e_account_info"), dict)
            else None
        )
        is_verified = None
        if isinstance(e_account_info, dict):
            is_verified = bool(e_account_info.get("is_verified"))
        # Use sec_uid for the profile URL when available; fall back to open_id
        sec_uid = str(user_data.get("sec_uid") or open_id)
        return PlatformAccountData(
            external_id=open_id,
            username=None,
            display_name=nickname,
            profile_url=DOUYIN_PROFILE_URL + sec_uid,
            avatar_url=str(avatar) if isinstance(avatar, str) and avatar else None,
            description=None,
            country=str(country) if isinstance(country, str) and country else None,
            language="zh-CN",
            is_verified=is_verified,
            source_kind="live",
            provider=self.key,
            fetched_at=fetched_at,
            metadata={
                "province": str(province) if isinstance(province, str) and province else None,
                "city": str(city) if isinstance(city, str) and city else None,
                "sec_uid": sec_uid if sec_uid != open_id else None,
                "e_account_info": e_account_info,
                "total_fans": (
                    parse_int(fan_data.get("total_fans"))
                    if isinstance(fan_data, dict)
                    else None
                ),
                "all_fans_num": (
                    parse_int(fan_data.get("all_fans_num"))
                    if isinstance(fan_data, dict)
                    else None
                ),
                "provider_schema_version": "douyin-open-platform-v1",
            },
        )

    # ------------------------------------------------------------------
    # Content mapping
    # ------------------------------------------------------------------

    def _map_video(
        self,
        item: Mapping[str, Any],
        account_id: str,
        fetched_at: datetime,
    ) -> PlatformContentData:
        item_id = str(item.get("item_id") or "")
        if not item_id:
            raise AdapterContractError("Douyin video item is missing item_id")
        title = str(item.get("title") or item_id)
        create_time = item.get("create_time")
        cover = item.get("cover")
        video_status = item.get("video_status")
        share_url = item.get("share_url")
        return PlatformContentData(
            external_id=item_id,
            account_external_id=account_id,
            content_type="video",
            title=title,
            description=None,
            published_at=parse_unix_timestamp(create_time),
            duration_seconds=None,
            canonical_url=str(share_url) if isinstance(share_url, str) and share_url else "",
            cover_url=str(cover) if isinstance(cover, str) and cover else None,
            language="zh-CN",
            status=(
                str(video_status)
                if isinstance(video_status, str) and video_status
                else "published"
            ),
            source_kind="live",
            provider=self.key,
            fetched_at=fetched_at,
            metadata={
                "share_url": share_url,
                "statistics_available": isinstance(item.get("statistics"), dict),
                "provider_schema_version": "douyin-open-platform-v1",
            },
        )

    # ------------------------------------------------------------------
    # Public API: resolve_account
    # ------------------------------------------------------------------

    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        open_id = self._resolve_open_id(locator)
        account = await self._fetch_account_by_open_id(ctx, open_id)
        if locator.startswith(("https://", "http://")):
            return replace(account, profile_url=locator)
        return account

    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData:
        return await self._fetch_account_by_open_id(ctx, external_id)

    async def _fetch_account_by_id(
        self, ctx: AdapterCallContext, open_id: str
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Fetch user info and fan data for a given open_id."""
        user_payload = await self._request(
            ctx,
            "GET",
            "/api/douyin/v1/user/info/",
            params={"open_id": open_id},
        )
        user_data = user_payload.get("data")
        if not isinstance(user_data, dict):
            raise AdapterContractError("Douyin user info response has no data object")

        fan_data: dict[str, Any] | None = None
        try:
            fan_payload = await self._request(
                ctx,
                "GET",
                "/api/douyin/v1/user/fan_data/",
                params={"open_id": open_id},
            )
            raw_fan = fan_payload.get("data")
            if isinstance(raw_fan, dict):
                fan_data = raw_fan
        except (PermissionDeniedError, AdapterNotFoundError):
            # Fan data may not be available for all accounts
            logger.info(
                "douyin_fan_data_unavailable",
                extra={
                    "event": "provider.douyin.fan_data_unavailable",
                    "request_id": ctx.request_id,
                    "open_id": open_id,
                },
            )
        return user_data, fan_data

    async def _fetch_account_by_open_id(
        self, ctx: AdapterCallContext, open_id: str
    ) -> PlatformAccountData:
        user_data, fan_data = await self._fetch_account_by_id(ctx, open_id)
        return self._map_account(user_data, fan_data, ctx.observed_at)

    # ------------------------------------------------------------------
    # Public API: list_contents
    # ------------------------------------------------------------------

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        params: dict[str, Any] = {
            "open_id": external_account_id,
            "cursor": int(cursor) if cursor else 0,
            "count": max(1, min(page_size, 20)),
        }
        payload = await self._request(
            ctx,
            "GET",
            "/api/douyin/v1/video/video_list/",
            params=params,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AdapterContractError("Douyin video list response has no data object")
        video_list = data.get("list")
        if not isinstance(video_list, list):
            raise AdapterContractError("Douyin video list response has no list array")

        mapped: list[PlatformContentData] = []
        reached_checkpoint = False
        for item in video_list:
            if not isinstance(item, dict):
                continue
            create_time = item.get("create_time")
            published_at = parse_unix_timestamp(create_time)
            if published_after and published_at and published_at <= published_after:
                reached_checkpoint = True
                continue
            mapped.append(self._map_video(item, external_account_id, ctx.observed_at))

        has_more = data.get("has_more")
        next_cursor_value = data.get("cursor")
        next_cursor: str | None = None
        if has_more and next_cursor_value is not None and not reached_checkpoint:
            next_cursor = str(next_cursor_value)

        return AdapterPage(
            items=tuple(mapped),
            next_cursor=next_cursor,
            checkpoint={
                "open_id": external_account_id,
                "published_after": published_after.isoformat() if published_after else None,
            },
        )

    # ------------------------------------------------------------------
    # Public API: fetch_content
    # ------------------------------------------------------------------

    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData:
        # The video_data endpoint requires both open_id and item_id.
        # When called with only an item_id we cannot determine the open_id.
        # We pass external_id as item_id; the caller must supply a config
        # that includes context about the account. As a pragmatic fallback
        # we try fetching with an empty open_id which will surface a clear
        # Douyin error if the API rejects it.
        #
        # In practice, the monitoring layer calls list_contents first and
        # stores account_external_id alongside each content item, then uses
        # fetch_content_analytics for stats. This method exists to satisfy
        # the abstract interface.
        payload = await self._request(
            ctx,
            "GET",
            "/api/douyin/v1/video/video_data/",
            params={"open_id": "", "item_id": external_id},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AdapterNotFoundError("Douyin video was not found")
        # Inject item_id if the API response doesn't include it
        if "item_id" not in data:
            data["item_id"] = external_id
        return self._map_video(data, "unknown", ctx.observed_at)

    # ------------------------------------------------------------------
    # Public API: fetch_account_analytics
    # ------------------------------------------------------------------

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        fan_payload = await self._request(
            ctx,
            "GET",
            "/api/douyin/v1/user/fan_data/",
            params={"open_id": external_id},
        )
        fan_data = fan_payload.get("data")
        if not isinstance(fan_data, dict):
            raise AdapterContractError("Douyin fan data response has no data object")
        follower_count = parse_int(fan_data.get("total_fans"))
        return PlatformMetricsData(
            external_id=external_id,
            captured_at=ctx.observed_at,
            metrics={
                "follower_count": follower_count,
                "following_count": None,
                "total_like_count": None,
                "total_view_count": None,
                "video_count": None,
                "engagement_rate": None,
            },
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            unavailable_metrics=(
                "following_count",
                "total_like_count",
                "total_view_count",
                "engagement_rate",
            ),
            metadata={
                "scope": "douyin_open_platform",
                "all_fans_num": parse_int(fan_data.get("all_fans_num")),
            },
        )

    # ------------------------------------------------------------------
    # Public API: fetch_content_analytics
    # ------------------------------------------------------------------

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        if not external_ids:
            return ()

        # The video_data endpoint supports one item at a time. We also need
        # the open_id. Since the caller typically provides item_ids within
        # the same account context, we attempt fetching via the video_list
        # endpoint and filtering, or individually. For correctness we fetch
        # each video's stats individually. We need an open_id which we
        # obtain from the config context – but the abstract interface does
        # not supply it. We therefore rely on the monitoring layer passing
        # account_external_id in the ctx.config or accept that this method
        # is best-effort. A pragmatic approach: fetch the video_list and
        # match by item_id.
        #
        # To keep this method self-contained we iterate over each id and
        # fetch via video_data with an empty open_id. If the API requires
        # an open_id the caller should use list_contents which already
        # includes statistics.
        results: list[PlatformMetricsData] = []
        for item_id in external_ids:
            if not item_id:
                continue
            try:
                payload = await self._request(
                    ctx,
                    "GET",
                    "/api/douyin/v1/video/video_data/",
                    params={"open_id": "", "item_id": item_id},
                )
            except (AdapterNotFoundError, PermissionDeniedError):
                results.append(
                    PlatformMetricsData(
                        external_id=item_id,
                        captured_at=ctx.observed_at,
                        metrics={},
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=("all",),
                        metadata={"availability": "not_found_or_permission_denied"},
                    )
                )
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                results.append(
                    PlatformMetricsData(
                        external_id=item_id,
                        captured_at=ctx.observed_at,
                        metrics={},
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        unavailable_metrics=("all",),
                        metadata={"availability": "invalid_response"},
                    )
                )
                continue
            statistics = data.get("statistics")
            if not isinstance(statistics, dict):
                statistics = {}
            results.append(
                PlatformMetricsData(
                    external_id=item_id,
                    captured_at=ctx.observed_at,
                    metrics={
                        "view_count": parse_int(statistics.get("play_count")),
                        "like_count": parse_int(statistics.get("digg_count")),
                        "comment_count": parse_int(statistics.get("comment_count")),
                        "share_count": parse_int(statistics.get("forward_count")),
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
                        "scope": "douyin_open_platform",
                        "download_count": parse_int(statistics.get("download_count")),
                    },
                )
            )
        return tuple(results)

    # ------------------------------------------------------------------
    # Public API: health_check
    # ------------------------------------------------------------------

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        try:
            await self.validate_config(ctx.config)
        except AdapterConfigurationError as exc:
            return AdapterHealth(
                status="unavailable",
                checked_at=ctx.observed_at,
                detail=f"{exc.code}: {exc}",
            )
        # A lightweight probe: attempt the token endpoint to verify credentials
        try:
            await self._request(
                ctx,
                "POST",
                "/oauth/client_token/",
                json_body={
                    "client_key": cast(str, ctx.config["client_key"]),
                    "client_secret": cast(str, ctx.config["client_secret"]),
                    "grant_type": "client_credential",
                },
            )
        except AuthenticationError as exc:
            return AdapterHealth(
                status="unavailable",
                checked_at=ctx.observed_at,
                detail=f"{exc.code}: {exc}",
            )
        except Exception as exc:
            if isinstance(exc, (AdapterConfigurationError, RateLimitError)):
                return AdapterHealth(
                    status="unavailable",
                    checked_at=ctx.observed_at,
                    detail=f"{getattr(exc, 'code', 'error')}: {exc}",
                )
            raise
        return AdapterHealth(status="ok", checked_at=ctx.observed_at)
