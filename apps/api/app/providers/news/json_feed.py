import asyncio
import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from urllib.parse import urljoin

import httpx

from app.providers.news.base import (
    NewsArticleData,
    NewsCallContext,
    NewsPage,
    NewsProvider,
    NewsProviderConfigurationError,
    NewsProviderContractError,
    NewsProviderHealth,
    NewsProviderRateLimitError,
    NewsProviderTransientError,
)
from app.providers.news.utils import (
    canonicalize_url,
    clean_text,
    ensure_public_endpoint,
    nested_value,
    parse_iso_datetime,
    validate_source_url,
)


class GenericJSONFeedProvider(NewsProvider):
    key = "generic_json"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        skip_dns_check: bool = False,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=False
        )
        self._owns_client = client is None
        self._max_attempts = max(1, min(max_attempts, 5))
        self._skip_dns_check = skip_dns_check

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def validate_source(self, config: Mapping[str, Any]) -> None:
        if not isinstance(config.get("url"), str):
            raise NewsProviderConfigurationError("JSON source requires a URL")
        try:
            validate_source_url(str(config["url"]))
        except ValueError as exc:
            raise NewsProviderConfigurationError(str(exc)) from exc
        mappings = config.get("field_mappings")
        if not isinstance(mappings, Mapping):
            raise NewsProviderConfigurationError("JSON source requires field_mappings")
        for required in ("title", "url"):
            if not isinstance(mappings.get(required), str):
                raise NewsProviderConfigurationError(f"JSON field_mappings requires {required}")

    async def _payload(self, ctx: NewsCallContext) -> Mapping[str, Any] | list[Any]:
        await self.validate_source(ctx.config)
        url = cast(str, ctx.config["url"])
        for attempt in range(1, self._max_attempts + 1):
            try:
                current_url = url
                for redirect_count in range(4):
                    if self._skip_dns_check:
                        await ensure_public_endpoint(current_url, skip_dns_check=True)
                    else:
                        await ensure_public_endpoint(current_url)
                    response = await self._client.get(
                        current_url,
                        headers={"Accept": "application/json", "X-Request-Id": ctx.request_id},
                        follow_redirects=False,
                    )
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    location = response.headers.get("location")
                    if not location or redirect_count == 3:
                        raise NewsProviderConfigurationError(
                            "JSON feed redirect chain is invalid or too long"
                        )
                    current_url = urljoin(current_url, location)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self._max_attempts:
                    raise NewsProviderTransientError(type(exc).__name__) from exc
                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
                continue
            except ValueError as exc:
                raise NewsProviderConfigurationError(str(exc)) from exc
            except OSError as exc:
                raise NewsProviderTransientError(str(exc)) from exc
            if response.status_code == 429:
                raise NewsProviderRateLimitError("JSON feed returned HTTP 429")
            if response.status_code >= 500 and attempt < self._max_attempts:
                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
                continue
            if not response.is_success:
                raise NewsProviderConfigurationError(
                    f"JSON feed returned HTTP {response.status_code}"
                )
            content_length = int(response.headers.get("content-length", "0") or 0)
            if content_length > 5_000_000 or len(response.content) > 5_000_000:
                raise NewsProviderContractError("JSON feed payload exceeds 5 MB")
            try:
                payload = response.json()
            except ValueError as exc:
                raise NewsProviderContractError("JSON feed returned invalid JSON") from exc
            if not isinstance(payload, (Mapping, list)):
                raise NewsProviderContractError("JSON feed root must be object or array")
            return payload
        raise NewsProviderTransientError("JSON feed retries exhausted")

    async def _all_items(self, ctx: NewsCallContext) -> list[NewsArticleData]:
        payload = await self._payload(ctx)
        items_path = str(ctx.config.get("items_path", "items"))
        raw_items: object = (
            payload if isinstance(payload, list) else nested_value(payload, items_path)
        )
        if not isinstance(raw_items, list):
            raise NewsProviderContractError("configured JSON items_path is not an array")
        return [
            await self.normalize_article(cast(Mapping[str, Any], item), ctx)
            for item in raw_items
            if isinstance(item, Mapping)
        ]

    async def fetch_latest(
        self, ctx: NewsCallContext, *, cursor: str | None, limit: int
    ) -> NewsPage:
        items = await self._all_items(ctx)
        offset = int(cursor or 0)
        selected = items[offset : offset + max(1, min(limit, 200))]
        next_offset = offset + len(selected)
        return NewsPage(
            items=tuple(selected),
            next_cursor=str(next_offset) if next_offset < len(items) else None,
        )

    async def fetch_range(
        self,
        ctx: NewsCallContext,
        *,
        start: datetime,
        end: datetime,
        cursor: str | None,
        limit: int,
    ) -> NewsPage:
        items = [
            item
            for item in await self._all_items(ctx)
            if item.published_at is not None and start <= item.published_at <= end
        ]
        offset = int(cursor or 0)
        selected = items[offset : offset + max(1, min(limit, 200))]
        next_offset = offset + len(selected)
        return NewsPage(
            items=tuple(selected),
            next_cursor=str(next_offset) if next_offset < len(items) else None,
        )

    async def normalize_article(
        self, raw: Mapping[str, Any], ctx: NewsCallContext
    ) -> NewsArticleData:
        mappings = cast(Mapping[str, str], ctx.config["field_mappings"])

        def value(key: str) -> object:
            path = mappings.get(key)
            return nested_value(raw, path) if path else None

        title = clean_text(value("title"), limit=1000)
        url_value = value("url")
        if title is None or not isinstance(url_value, str):
            raise NewsProviderContractError("JSON item requires mapped title and URL")
        canonical_url = canonicalize_url(url_value)
        external_value = value("id")
        external_id = (
            str(external_value)
            if external_value is not None
            else hashlib.sha256(canonical_url.encode()).hexdigest()
        )
        return NewsArticleData(
            external_id=external_id,
            canonical_url=canonical_url,
            title=title,
            summary=clean_text(value("summary"), limit=20_000),
            content=clean_text(value("content"), limit=100_000),
            author=clean_text(value("author"), limit=255),
            published_at=parse_iso_datetime(value("published_at")),
            event_time=parse_iso_datetime(value("event_time")),
            language=clean_text(value("language"), limit=16)
            or (str(ctx.config.get("language")) if ctx.config.get("language") else None),
            sport=clean_text(value("sport"), limit=120)
            or (str(ctx.config.get("sport")) if ctx.config.get("sport") else None),
            league=clean_text(value("league"), limit=120),
            country=clean_text(value("country"), limit=2)
            or (str(ctx.config.get("country")) if ctx.config.get("country") else None),
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.fetched_at,
            metadata={"published_at_reported": value("published_at") is not None},
        )

    async def health_check(self, ctx: NewsCallContext) -> NewsProviderHealth:
        await self.fetch_latest(ctx, cursor=None, limit=1)
        return NewsProviderHealth(status="ok", checked_at=ctx.fetched_at)
