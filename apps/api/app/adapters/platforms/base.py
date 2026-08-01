from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal


class AdapterCapability(StrEnum):
    PUBLIC_PROFILE = "PUBLIC_PROFILE"
    ACCOUNT_ANALYTICS = "ACCOUNT_ANALYTICS"
    CONTENT_LIST = "CONTENT_LIST"
    CONTENT_ANALYTICS = "CONTENT_ANALYTICS"
    TRAFFIC_SOURCES = "TRAFFIC_SOURCES"
    RETENTION = "RETENTION"
    REVENUE = "REVENUE"
    COMMENTS = "COMMENTS"
    SEARCH_TERMS = "SEARCH_TERMS"


@dataclass(frozen=True)
class AdapterConfigField:
    key: str
    label: str
    required: bool
    secret: bool = False
    description: str | None = None


@dataclass(frozen=True)
class AdapterDescriptor:
    key: str
    name: str
    implementation_status: Literal["implemented", "skeleton"]
    capabilities: Mapping[AdapterCapability, bool]
    config_fields: tuple[AdapterConfigField, ...]
    source_kinds: frozenset[Literal["live"]]


@dataclass(frozen=True)
class AdapterCallContext:
    config: Mapping[str, Any]
    observed_at: datetime
    request_id: str


@dataclass(frozen=True)
class PlatformAccountData:
    external_id: str
    username: str | None
    display_name: str
    profile_url: str | None
    avatar_url: str | None
    description: str | None
    country: str | None
    language: str | None
    is_verified: bool | None
    source_kind: Literal["live"]
    provider: str
    fetched_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformContentData:
    external_id: str
    account_external_id: str
    content_type: str
    title: str
    description: str | None
    published_at: datetime | None
    duration_seconds: float | None
    canonical_url: str
    cover_url: str | None
    language: str | None
    status: str
    source_kind: Literal["live"]
    provider: str
    fetched_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformMetricsData:
    external_id: str
    captured_at: datetime
    metrics: Mapping[str, int | float | None]
    source_kind: Literal["live"]
    provider: str
    fetched_at: datetime
    unavailable_metrics: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterPage:
    items: tuple[PlatformContentData, ...]
    next_cursor: str | None
    checkpoint: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterHealth:
    status: Literal["ok", "degraded", "unavailable"]
    checked_at: datetime
    detail: str | None = None


class PlatformAdapterError(Exception):
    code = "platform_adapter_error"
    retryable = False


class AdapterConfigurationError(PlatformAdapterError):
    code = "adapter_configuration_error"


class AuthenticationError(PlatformAdapterError):
    code = "authentication_error"


class PermissionDeniedError(PlatformAdapterError):
    code = "permission_denied"


class AdapterNotFoundError(PlatformAdapterError):
    code = "not_found"


class RateLimitError(PlatformAdapterError):
    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TransientAdapterError(PlatformAdapterError):
    code = "transient_provider_error"
    retryable = True


class AdapterContractError(PlatformAdapterError):
    code = "contract_mapping_error"


class CapabilityNotSupportedError(PlatformAdapterError):
    code = "capability_not_supported"


class AdapterNotImplementedError(PlatformAdapterError):
    code = "adapter_not_implemented"


class PlatformAdapter(ABC):
    descriptor: AdapterDescriptor

    @property
    def key(self) -> str:
        return self.descriptor.key

    @abstractmethod
    async def validate_config(self, config: Mapping[str, Any]) -> None: ...

    @abstractmethod
    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData: ...

    @abstractmethod
    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData: ...

    @abstractmethod
    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage: ...

    @abstractmethod
    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData: ...

    @abstractmethod
    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData: ...

    @abstractmethod
    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]: ...

    @abstractmethod
    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth: ...
