from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterConfigField,
    AdapterDescriptor,
    AdapterHealth,
    AdapterNotImplementedError,
    AdapterPage,
    PlatformAccountData,
    PlatformAdapter,
    PlatformContentData,
    PlatformMetricsData,
)


class SkeletonPlatformAdapter(PlatformAdapter):
    async def validate_config(self, config: Mapping[str, Any]) -> None:
        missing = [
            field.key
            for field in self.descriptor.config_fields
            if field.required and not config.get(field.key)
        ]
        if missing:
            raise AdapterNotImplementedError(
                f"{self.key} adapter skeleton requires configuration: {', '.join(missing)}"
            )
        raise AdapterNotImplementedError(f"{self.key} adapter is a declared skeleton")

    def _not_implemented(self) -> AdapterNotImplementedError:
        return AdapterNotImplementedError(
            f"{self.key} adapter has no live implementation and returned no platform data"
        )

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        raise self._not_implemented()

    async def fetch_account(self, ctx: AdapterCallContext, external_id: str) -> PlatformAccountData:
        raise self._not_implemented()

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        raise self._not_implemented()

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        raise self._not_implemented()

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        raise self._not_implemented()

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        raise self._not_implemented()

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        return AdapterHealth(
            status="unavailable",
            checked_at=ctx.observed_at,
            detail=f"{self.key} is a skeleton and performs no live requests",
        )


NO_CAPABILITIES = {capability: False for capability in AdapterCapability}


class TikTokAdapter(SkeletonPlatformAdapter):
    descriptor = AdapterDescriptor(
        key="tiktok",
        name="TikTok（骨架）",
        implementation_status="skeleton",
        capabilities=NO_CAPABILITIES,
        config_fields=(
            AdapterConfigField("client_key", "Client Key", True),
            AdapterConfigField("client_secret", "Client Secret", True, secret=True),
            AdapterConfigField("access_token", "Access Token", True, secret=True),
        ),
        source_kinds=frozenset({"live"}),
    )


class DouyinAdapter(SkeletonPlatformAdapter):
    descriptor = AdapterDescriptor(
        key="douyin",
        name="抖音（骨架）",
        implementation_status="skeleton",
        capabilities=NO_CAPABILITIES,
        config_fields=(
            AdapterConfigField("client_key", "Client Key", True),
            AdapterConfigField("client_secret", "Client Secret", True, secret=True),
            AdapterConfigField("access_token", "Access Token", True, secret=True),
        ),
        source_kinds=frozenset({"live"}),
    )


class BilibiliAdapter(SkeletonPlatformAdapter):
    descriptor = AdapterDescriptor(
        key="bilibili",
        name="Bilibili（骨架）",
        implementation_status="skeleton",
        capabilities=NO_CAPABILITIES,
        config_fields=(
            AdapterConfigField(
                "authorized_api_config",
                "Authorized API Configuration",
                True,
                secret=True,
            ),
        ),
        source_kinds=frozenset({"live"}),
    )
