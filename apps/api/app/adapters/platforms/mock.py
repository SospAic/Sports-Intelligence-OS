import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterConfigField,
    AdapterConfigurationError,
    AdapterDescriptor,
    AdapterHealth,
    AdapterPage,
    PlatformAccountData,
    PlatformAdapter,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)


def stable_number(value: str, lower: int, upper: int) -> int:
    digest = hashlib.sha256(value.encode()).digest()
    return lower + int.from_bytes(digest[:8], "big") % (upper - lower + 1)


class MockPlatformAdapter(PlatformAdapter):
    descriptor = AdapterDescriptor(
        key="mock_platform",
        name="Mock Platform（模拟数据）",
        implementation_status="implemented",
        capabilities={
            AdapterCapability.PUBLIC_PROFILE: True,
            AdapterCapability.ACCOUNT_ANALYTICS: True,
            AdapterCapability.CONTENT_LIST: True,
            AdapterCapability.CONTENT_ANALYTICS: True,
            AdapterCapability.TRAFFIC_SOURCES: True,
            AdapterCapability.RETENTION: True,
            AdapterCapability.REVENUE: True,
            AdapterCapability.COMMENTS: False,
            AdapterCapability.SEARCH_TERMS: True,
        },
        config_fields=(
            AdapterConfigField(
                key="seed",
                label="确定性 Seed",
                required=False,
                description="相同 Seed 产生相同数据",
            ),
            AdapterConfigField(
                key="snapshot_index",
                label="增长步数",
                required=False,
                description="非负整数，用于稳定模拟增长",
            ),
            AdapterConfigField(
                key="simulate_error",
                label="模拟错误",
                required=False,
                description="设置为 transient 可验证失败和重试",
            ),
        ),
        source_kinds=frozenset({"mock"}),
    )

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        snapshot_index = config.get("snapshot_index", 0)
        if not isinstance(snapshot_index, int) or snapshot_index < 0:
            raise AdapterConfigurationError("mock snapshot_index must be a non-negative integer")
        if config.get("simulate_error") not in {None, "transient"}:
            raise AdapterConfigurationError("mock simulate_error must be 'transient' when set")

    async def _prepare(self, ctx: AdapterCallContext) -> tuple[str, int]:
        await self.validate_config(ctx.config)
        if ctx.config.get("simulate_error") == "transient":
            raise TransientAdapterError("Mock adapter simulated a transient failure")
        return str(ctx.config.get("seed", "sports-intelligence-demo")), int(
            ctx.config.get("snapshot_index", 0)
        )

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        seed, _ = await self._prepare(ctx)
        token = (
            locator.removeprefix("mock-account-")
            if locator.startswith("mock-account-")
            else hashlib.sha256(f"{seed}:{locator}".encode()).hexdigest()[:12]
        )
        return PlatformAccountData(
            external_id=f"mock-account-{token}",
            username=f"mock_creator_{token[:6]}",
            display_name=f"Demo Mock Creator {token[:6]}（模拟数据）",
            profile_url=f"https://example.invalid/mock/accounts/{token}",
            avatar_url=None,
            description="Deterministic synthetic account; not data from any real platform.",
            country="ZZ",
            language="en",
            is_verified=False,
            source_kind="mock",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={"demo": True, "is_mock": True, "seed_fingerprint": token},
        )

    async def fetch_account(self, ctx: AdapterCallContext, external_id: str) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        seed, _ = await self._prepare(ctx)
        offset = int(cursor or 0)
        count = max(1, min(page_size, 50))
        items: list[PlatformContentData] = []
        for index in range(offset, min(offset + count, 12)):
            published_at = ctx.observed_at - timedelta(hours=index * 8 + 1)
            if published_after is not None and published_at <= published_after:
                break
            token = hashlib.sha256(
                f"{seed}:{external_account_id}:content:{index}".encode()
            ).hexdigest()[:12]
            items.append(
                PlatformContentData(
                    external_id=f"mock-content-{token}",
                    account_external_id=external_account_id,
                    content_type="video",
                    title=f"Demo Mock Sports Clip {index + 1}（模拟作品）",
                    description="Synthetic content generated only for development and tests.",
                    published_at=published_at,
                    duration_seconds=float(30 + index * 3),
                    canonical_url=f"https://example.invalid/mock/contents/{token}",
                    cover_url=None,
                    language="en",
                    status="published",
                    source_kind="mock",
                    provider=self.key,
                    fetched_at=ctx.observed_at,
                    metadata={"demo": True, "is_mock": True, "sequence": index},
                )
            )
        next_offset = offset + len(items)
        next_cursor = str(next_offset) if next_offset < 12 and len(items) == count else None
        return AdapterPage(
            items=tuple(items),
            next_cursor=next_cursor,
            checkpoint={"offset": next_offset, "source_kind": "mock"},
        )

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        seed, _ = await self._prepare(ctx)
        index = stable_number(f"{seed}:{external_id}", 0, 11)
        return PlatformContentData(
            external_id=external_id,
            account_external_id=f"mock-account-{hashlib.sha256(seed.encode()).hexdigest()[:12]}",
            content_type="video",
            title=f"Demo Mock Sports Clip {index + 1}（模拟作品）",
            description="Synthetic content generated only for development and tests.",
            published_at=ctx.observed_at - timedelta(hours=index * 8 + 1),
            duration_seconds=float(30 + index * 3),
            canonical_url=f"https://example.invalid/mock/contents/{external_id}",
            cover_url=None,
            language="en",
            status="published",
            source_kind="mock",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={"demo": True, "is_mock": True, "sequence": index},
        )

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        seed, step = await self._prepare(ctx)
        base = stable_number(f"{seed}:{external_id}:followers", 5_000, 50_000)
        followers = base + step * 250
        return PlatformMetricsData(
            external_id=external_id,
            captured_at=ctx.observed_at,
            metrics={
                "follower_count": followers,
                "following_count": stable_number(f"{seed}:following", 10, 500),
                "total_like_count": followers * 24 + step * 10_000,
                "total_view_count": followers * 420 + step * 250_000,
                "video_count": 12,
                "engagement_rate": 0.0875,
            },
            source_kind="mock",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={"demo": True, "is_mock": True, "snapshot_index": step},
        )

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        seed, step = await self._prepare(ctx)
        results: list[PlatformMetricsData] = []
        for external_id in external_ids:
            base_views = stable_number(f"{seed}:{external_id}:views", 10_000, 1_500_000)
            views = base_views + step * 25_000
            results.append(
                PlatformMetricsData(
                    external_id=external_id,
                    captured_at=ctx.observed_at,
                    metrics={
                        "view_count": views,
                        "like_count": int(views * 0.08),
                        "comment_count": int(views * 0.006),
                        "share_count": int(views * 0.012),
                        "favorite_count": int(views * 0.018),
                        "follower_gain": int(views * 0.001),
                        "average_watch_time": 36.5,
                        "completion_rate": 0.76,
                        "search_traffic_rate": 0.18,
                        "recommendation_traffic_rate": 0.70,
                        "profile_traffic_rate": 0.12,
                        "revenue": round(views / 1000 * 1.2, 2),
                        "rpm": 1.2,
                    },
                    source_kind="mock",
                    provider=self.key,
                    fetched_at=ctx.observed_at,
                    metadata={"demo": True, "is_mock": True, "snapshot_index": step},
                )
            )
        return tuple(results)

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        await self._prepare(ctx)
        return AdapterHealth(
            status="ok",
            checked_at=ctx.observed_at,
            detail="Mock adapter is deterministic synthetic data, not a real platform.",
        )
