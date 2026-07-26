import asyncio
import calendar
from collections.abc import Mapping
from datetime import UTC, datetime
from time import struct_time
from typing import Any, cast

import feedparser  # type: ignore[import-untyped]
import httpx

from app.providers.news.base import (
    NewsArticleData,
    NewsCallContext,
    NewsPage,
    NewsProvider,
    NewsProviderAuthenticationError,
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
    validate_source_url,
)


def _feed_datetime(value: object) -> datetime | None:
    if not isinstance(value, struct_time):
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)


class FeedProvider(NewsProvider):
    expected_family: str

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._owns_client = client is None
        self._max_attempts = max(1, min(max_attempts, 5))
        self._retry_base_seconds = max(0.0, retry_base_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def validate_source(self, config: Mapping[str, Any]) -> None:
        url = config.get("url")
        if not isinstance(url, str):
            raise NewsProviderConfigurationError("feed source requires a URL")
        try:
            validate_source_url(url)
        except ValueError as exc:
            raise NewsProviderConfigurationError(str(exc)) from exc

    async def _download(self, ctx: NewsCallContext) -> bytes:
        await self.validate_source(ctx.config)
        url = cast(str, ctx.config["url"])
        try:
            await ensure_public_endpoint(url)
        except ValueError as exc:
            raise NewsProviderConfigurationError(str(exc)) from exc
        except OSError as exc:
            raise NewsProviderTransientError(str(exc)) from exc
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.get(
                    url,
                    headers={
                        "Accept": "application/atom+xml, application/rss+xml, application/xml",
                        "User-Agent": "Sports-Intelligence-OS/0.1 feed reader",
                        "X-Request-Id": ctx.request_id,
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self._max_attempts:
                    raise NewsProviderTransientError(type(exc).__name__) from exc
                await asyncio.sleep(self._retry_base_seconds * (2 ** (attempt - 1)))
                continue
            if response.is_success:
                return response.content
            if response.status_code in {401, 403}:
                raise NewsProviderAuthenticationError(f"feed returned HTTP {response.status_code}")
            if response.status_code == 429:
                raise NewsProviderRateLimitError("feed returned HTTP 429")
            if response.status_code >= 500 and attempt < self._max_attempts:
                await asyncio.sleep(self._retry_base_seconds * (2 ** (attempt - 1)))
                continue
            if response.status_code >= 500:
                raise NewsProviderTransientError(f"feed returned HTTP {response.status_code}")
            raise NewsProviderConfigurationError(f"feed returned HTTP {response.status_code}")
        raise NewsProviderTransientError("feed retries exhausted")

    async def _all_items(self, ctx: NewsCallContext) -> list[NewsArticleData]:
        parsed = feedparser.parse(await self._download(ctx))
        version = str(parsed.get("version") or "").casefold()
        if self.expected_family not in version:
            raise NewsProviderContractError(
                f"expected {self.expected_family} feed but detected {version or 'unknown'}"
            )
        entries = parsed.get("entries")
        if not isinstance(entries, list):
            raise NewsProviderContractError("feed entries are missing")
        return [
            await self.normalize_article(cast(Mapping[str, Any], entry), ctx) for entry in entries
        ]

    async def fetch_latest(
        self, ctx: NewsCallContext, *, cursor: str | None, limit: int
    ) -> NewsPage:
        items = await self._all_items(ctx)
        offset = int(cursor or 0)
        page_items = items[offset : offset + max(1, min(limit, 200))]
        next_offset = offset + len(page_items)
        return NewsPage(
            items=tuple(page_items),
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
        page_items = items[offset : offset + max(1, min(limit, 200))]
        next_offset = offset + len(page_items)
        return NewsPage(
            items=tuple(page_items),
            next_cursor=str(next_offset) if next_offset < len(items) else None,
        )

    async def normalize_article(
        self, raw: Mapping[str, Any], ctx: NewsCallContext
    ) -> NewsArticleData:
        link = raw.get("link")
        title = clean_text(raw.get("title"), limit=1000)
        if not isinstance(link, str) or title is None:
            raise NewsProviderContractError("feed entry requires title and link")
        canonical_url = canonicalize_url(link)
        external = raw.get("id") or raw.get("guid") or canonical_url
        content_blocks = raw.get("content")
        content_value: object = None
        if isinstance(content_blocks, list) and content_blocks:
            first = content_blocks[0]
            if isinstance(first, Mapping):
                content_value = first.get("value")
        published_at = _feed_datetime(raw.get("published_parsed")) or _feed_datetime(
            raw.get("updated_parsed")
        )
        return NewsArticleData(
            external_id=str(external),
            canonical_url=canonical_url,
            title=title,
            summary=clean_text(raw.get("summary"), limit=20_000),
            content=clean_text(content_value, limit=100_000),
            author=clean_text(raw.get("author"), limit=255),
            published_at=published_at,
            event_time=None,
            language=str(ctx.config.get("language")) if ctx.config.get("language") else None,
            sport=str(ctx.config.get("sport")) if ctx.config.get("sport") else None,
            league=str(ctx.config.get("league")) if ctx.config.get("league") else None,
            country=str(ctx.config.get("country")) if ctx.config.get("country") else None,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.fetched_at,
            metadata={
                "feed_version": self.expected_family,
                "published_at_reported": published_at is not None,
            },
        )

    async def health_check(self, ctx: NewsCallContext) -> NewsProviderHealth:
        try:
            await self.fetch_latest(ctx, cursor=None, limit=1)
        except Exception as exc:
            if isinstance(exc, (NewsProviderConfigurationError, NewsProviderAuthenticationError)):
                return NewsProviderHealth(
                    status="unavailable",
                    checked_at=ctx.fetched_at,
                    detail=f"{getattr(exc, 'code', 'error')}: {exc}",
                )
            raise
        return NewsProviderHealth(status="ok", checked_at=ctx.fetched_at)


class RSSProvider(FeedProvider):
    key = "rss"
    expected_family = "rss"


class AtomProvider(FeedProvider):
    key = "atom"
    expected_family = "atom"
