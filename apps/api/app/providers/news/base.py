from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class NewsCallContext:
    config: Mapping[str, Any]
    fetched_at: datetime
    request_id: str


@dataclass(frozen=True)
class NewsArticleData:
    external_id: str
    canonical_url: str
    title: str
    summary: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    event_time: datetime | None
    language: str | None
    sport: str | None
    league: str | None
    country: str | None
    source_kind: Literal["live", "imported"]
    provider: str
    fetched_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsPage:
    items: tuple[NewsArticleData, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class NewsProviderHealth:
    status: Literal["ok", "degraded", "unavailable"]
    checked_at: datetime
    detail: str | None = None


class NewsProviderError(Exception):
    code = "news_provider_error"
    retryable = False


class NewsProviderConfigurationError(NewsProviderError):
    code = "news_provider_configuration_error"


class NewsProviderAuthenticationError(NewsProviderError):
    code = "news_provider_authentication_error"


class NewsProviderRateLimitError(NewsProviderError):
    code = "news_provider_rate_limited"
    retryable = True


class NewsProviderTransientError(NewsProviderError):
    code = "news_provider_transient_error"
    retryable = True


class NewsProviderContractError(NewsProviderError):
    code = "news_provider_contract_error"


class NewsProviderCapabilityError(NewsProviderError):
    code = "news_provider_capability_not_supported"


class NewsProvider(ABC):
    key: str

    @abstractmethod
    async def validate_source(self, config: Mapping[str, Any]) -> None: ...

    @abstractmethod
    async def fetch_latest(
        self,
        ctx: NewsCallContext,
        *,
        cursor: str | None,
        limit: int,
    ) -> NewsPage: ...

    @abstractmethod
    async def fetch_range(
        self,
        ctx: NewsCallContext,
        *,
        start: datetime,
        end: datetime,
        cursor: str | None,
        limit: int,
    ) -> NewsPage: ...

    @abstractmethod
    async def normalize_article(
        self, raw: Mapping[str, Any], ctx: NewsCallContext
    ) -> NewsArticleData: ...

    @abstractmethod
    async def health_check(self, ctx: NewsCallContext) -> NewsProviderHealth: ...
