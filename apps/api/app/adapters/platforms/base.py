import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal


def parse_compact_count(text: str | None) -> int | None:
    """Parse compact count strings into an integer.

    Handles '1.2M', '456K', '1,234,567', '789' and trailing words such as
    'views' / '播放' / '次观看'. Also handles Chinese compact suffixes
    '万' (1e4) and '亿' (1e8) as in '1.2万', '3.4亿', '1.2万亿' — these appear
    throughout Douyin/Bilibili UIs. Returns ``None`` when nothing parseable.
    """
    if not text:
        return None
    t = text.strip().upper().replace(",", "")
    t = re.sub(r"[^0-9.KMB万亿]", "", t)
    m = re.match(r"([\d.]+)\s*([KMB万万亿]*)", t)
    if not m:
        return None
    num = float(m.group(1))
    mult = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "万": 10_000,
        "亿": 100_000_000,
        "万亿": 1_000_000_000_000,
    }.get(m.group(2), 1)
    return int(num * mult)


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
    # Optional callable that receives live yt-dlp stderr lines (one call per
    # line) so a sync executor can surface them as a scrolling runtime log.
    # Carried on the per-call context (never on the shared adapter instance) so
    # concurrent syncs never clobber each other's sink.
    progress_sink: Any | None = None
    # ── Fast-listing hints (see YtDlpAdapter.list_contents) ──────────────────
    # External ids already stored for this account. An adapter that supports a
    # cheap "enumerate first, extract later" strategy uses this to skip the
    # expensive per-video extraction for works we already know about.
    known_external_ids: frozenset[str] = frozenset()
    # Whether the workspace sync policy wants known works left untouched. When
    # False the adapter must still fetch full detail for known works so their
    # metadata can be refreshed.
    skip_known: bool = False
    # Maximum number of concurrent per-video extractions. 1 keeps the strictly
    # sequential behaviour; higher values trade anti-bot risk for wall clock.
    fetch_concurrency: int = 1


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
    # Optional local media produced by a download-capable adapter (yt-dlp).
    # ``None`` means no files were archived. When present it carries the
    # workspace-relative directory plus the discovered file basenames:
    #   {"base": "<workspace_id>/<account>/<external_id>",
    #    "thumbnail": "id.webp", "video": "id.mp4", "info_json": "id.info.json",
    #    "subtitles": [{"lang": "zh-Hans", "file": "id.zh-Hans.vtt"}]}
    media: Mapping[str, Any] | None = None
    # Creator-assigned / platform-extracted topic tags (yt-dlp "tags", YouTube
    # snippet tags, ...). Surfaced in the works-data multi-select filter.
    tags: Sequence[str] = field(default_factory=list)


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


class LoginRequiredError(PlatformAdapterError):
    """Raised when login, CAPTCHA, or an interactive security step blocks access.

    Permanent by definition: without credentials the request can never succeed,
    so retrying only burns the scheduler's budget and delays the one thing that
    actually fixes it — the operator configuring a cookie. Lives here rather
    than in ``browser_base`` so yt-dlp and other non-browser adapters can raise
    it without importing Playwright.
    """

    code = "login_required"
    retryable = False

    def __init__(self, platform: str, detail: str = ""):
        msg = f"平台 {platform} 要求登录后才能访问该数据；公开页采集已停止，请改用官方 API/OAuth。"
        if detail:
            msg += f"（{detail}）"
        super().__init__(msg)
        self.platform = platform


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

    async def aclose(self) -> None:
        """Release resources held by the adapter (browsers, subprocesses, ...).

        Stateless adapters can rely on this no-op default; adapters that spawn
        browsers, child processes, or network sessions should override it.
        """
        return None
