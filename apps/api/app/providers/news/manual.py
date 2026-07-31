import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.providers.news.base import (
    NewsArticleData,
    NewsCallContext,
    NewsPage,
    NewsProvider,
    NewsProviderCapabilityError,
    NewsProviderConfigurationError,
    NewsProviderContractError,
    NewsProviderHealth,
)
from app.providers.news.utils import canonicalize_url, clean_text, parse_iso_datetime


class ManualNewsProvider(NewsProvider):
    key = "manual_news"

    async def validate_source(self, config: Mapping[str, Any]) -> None:
        if config.get("url") not in {None, ""}:
            raise NewsProviderConfigurationError("manual source must not configure a polling URL")

    async def fetch_latest(
        self, ctx: NewsCallContext, *, cursor: str | None, limit: int
    ) -> NewsPage:
        raise NewsProviderCapabilityError("manual source cannot be polled")

    async def fetch_range(
        self,
        ctx: NewsCallContext,
        *,
        start: datetime,
        end: datetime,
        cursor: str | None,
        limit: int,
    ) -> NewsPage:
        raise NewsProviderCapabilityError("manual source cannot be polled")

    async def normalize_article(
        self, raw: Mapping[str, Any], ctx: NewsCallContext
    ) -> NewsArticleData:
        title = clean_text(raw.get("title"), limit=1000)
        url = raw.get("canonical_url")
        if title is None or not isinstance(url, str):
            raise NewsProviderContractError("manual article requires title and canonical_url")
        canonical_url = canonicalize_url(url)
        external_id = str(
            raw.get("external_id") or hashlib.sha256(canonical_url.encode()).hexdigest()
        )
        return NewsArticleData(
            external_id=external_id,
            canonical_url=canonical_url,
            title=title,
            summary=clean_text(raw.get("summary"), limit=20_000),
            content=clean_text(raw.get("content"), limit=100_000),
            author=clean_text(raw.get("author"), limit=255),
            published_at=parse_iso_datetime(raw.get("published_at")),
            event_time=parse_iso_datetime(raw.get("event_time")),
            language=clean_text(raw.get("language"), limit=16),
            sport=clean_text(raw.get("sport"), limit=120),
            league=clean_text(raw.get("league"), limit=120),
            country=clean_text(raw.get("country"), limit=2),
            source_kind="imported",
            provider=self.key,
            fetched_at=ctx.fetched_at,
            metadata={"input_mode": "manual"},
        )

    async def health_check(self, ctx: NewsCallContext) -> NewsProviderHealth:
        return NewsProviderHealth(
            status="ok", checked_at=ctx.fetched_at, detail="manual entry requires no network"
        )
