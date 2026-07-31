import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms import (
    BilibiliBrowserAdapter,
    DouyinAdapter,
    DouyinBrowserAdapter,
    TikTokAdapter,
    TikTokBrowserAdapter,
    YouTubeAdapter,
    YouTubeBrowserAdapter,
)
from app.adapters.platforms.base import AdapterDescriptor
from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
    Platform,
)

logger = logging.getLogger(__name__)

# Maps platform key → adapter descriptor.  Every entry in PLATFORM_CATALOG
# that has a real adapter should appear here so that the seed function can
# derive capabilities from the implementation rather than hardcoding them.
_ADAPTER_DESCRIPTORS: dict[str, AdapterDescriptor] = {
    adapter_cls.descriptor.key: adapter_cls.descriptor
    for adapter_cls in (
        YouTubeAdapter,
        TikTokAdapter,
        DouyinAdapter,
        BilibiliBrowserAdapter,
        YouTubeBrowserAdapter,
        TikTokBrowserAdapter,
        DouyinBrowserAdapter,
    )
}

# (key, name, category, adapter_key)
# The 4 main platforms use browser-simulation adapters by default so that
# monitoring works without API keys. Browser scraping is the underlying
# mechanism — users only see the platform name, not "浏览器模拟".
PLATFORM_CATALOG = (
    ("youtube", "YouTube", "video", "youtube_browser"),
    ("tiktok", "TikTok", "video", "tiktok_browser"),
    ("douyin", "抖音", "video", "douyin_browser"),
    ("bilibili", "Bilibili", "video", "bilibili_browser"),
)
DEMO_CAPTURED_AT = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def stable_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sports-intelligence-os:{value}")


def _capabilities_from_descriptor(descriptor: AdapterDescriptor) -> dict[str, Any]:
    """Build the JSON-serialisable capabilities dict from an adapter descriptor."""
    reported = [
        capability.value
        for capability, supported in descriptor.capabilities.items()
        if supported
    ]
    return {
        "implementation_status": descriptor.implementation_status,
        "reported": reported,
        "private_analytics": "unavailable_not_fabricated",
    }


async def seed_platform_catalog(session: AsyncSession) -> tuple[int, int]:
    """Seed or update platform records from the catalog and adapter descriptors.

    Returns a ``(created, updated)`` count tuple so callers can report both
    new inserts and capability synchronisations.
    """
    created = 0
    updated = 0
    for key, name, category, adapter_key in PLATFORM_CATALOG:
        descriptor = _ADAPTER_DESCRIPTORS.get(key)
        if descriptor is not None:
            capabilities = _capabilities_from_descriptor(descriptor)
            # Prefer the descriptor's adapter key when available.
            effective_adapter_key = descriptor.key
        else:
            capabilities = {
                "implementation_status": "skeleton",
                "reported": [],
                "private_analytics": "unavailable_not_fabricated",
            }
            effective_adapter_key = adapter_key

        existing = await session.scalar(select(Platform).where(Platform.key == key))
        if existing is not None:
            changed = False
            if existing.adapter_key != effective_adapter_key:
                existing.adapter_key = effective_adapter_key
                changed = True
            if existing.capabilities != capabilities:
                existing.capabilities = capabilities
                changed = True
            if changed:
                updated += 1
                logger.info(
                    "platform_capabilities_updated",
                    extra={
                        "event": "seed.platform.updated",
                        "platform_key": key,
                        "adapter_key": effective_adapter_key,
                        "capabilities": capabilities,
                    },
                )
            continue
        session.add(
            Platform(
                id=stable_uuid(f"platform:{key}"),
                key=key,
                name=name,
                category=category,
                enabled=True,
                adapter_key=effective_adapter_key,
                capabilities=capabilities,
            )
        )
        created += 1
    await session.commit()
    return created, updated


async def seed_demo_monitoring(session: AsyncSession, workspace_id: UUID) -> dict[str, int]:
    platform = await session.scalar(select(Platform).where(Platform.key == "demo_mock"))
    if platform is None:
        platform = Platform(
            id=stable_uuid("platform:demo_mock"),
            key="demo_mock",
            name="Demo Mock Platform（模拟数据）",
            category="development",
            enabled=True,
            adapter_key="mock_platform",
            capabilities={
                "implementation_status": "demo_only",
                "source_kind": "mock",
                "reported": ["public_profile", "content_list", "content_analytics"],
            },
        )
        session.add(platform)
        await session.flush()

    account_id = stable_uuid(f"demo-account:{workspace_id}")
    account = await session.get(Account, account_id)
    created_accounts = 0
    if account is None:
        account = Account(
            id=account_id,
            workspace_id=workspace_id,
            platform_id=platform.id,
            external_id="demo-mock-account-001",
            username="demo_mock_creator",
            display_name="Demo 体育创作者（模拟数据）",
            profile_url="https://example.invalid/demo-mock-account-001",
            avatar_url=None,
            description="仅用于本地开发和测试的合成账号，不代表任何真实平台或人物。",
            country="ZZ",
            language="zh-CN",
            is_verified=False,
            is_active=True,
            metadata_json={"demo": True, "is_mock": True, "generator_version": "1"},
            last_synced_at=DEMO_CAPTURED_AT,
            sync_status="success",
            source_kind="mock",
            source_provider="mock_platform",
            fetched_at=DEMO_CAPTURED_AT,
            source_url=None,
            raw_payload_ref=None,
        )
        session.add(account)
        session.add(
            AccountSnapshot(
                id=stable_uuid(f"demo-account-snapshot:{workspace_id}"),
                account_id=account_id,
                captured_at=DEMO_CAPTURED_AT,
                follower_count=12500,
                following_count=42,
                total_like_count=420000,
                total_view_count=8_400_000,
                video_count=64,
                engagement_rate=Decimal("0.08750000"),
                metadata_json={"demo": True, "is_mock": True},
                source_kind="mock",
                source_provider="mock_platform",
                fetched_at=DEMO_CAPTURED_AT,
                raw_payload_ref=None,
                created_at=DEMO_CAPTURED_AT,
            )
        )
        created_accounts = 1

    content_id = stable_uuid(f"demo-content:{workspace_id}")
    content = await session.get(ContentItem, content_id)
    created_contents = 0
    if content is None:
        content = ContentItem(
            id=content_id,
            workspace_id=workspace_id,
            platform_id=platform.id,
            account_id=account_id,
            external_id="demo-mock-content-001",
            content_type="video",
            title="Demo：终场前的逆转（模拟作品）",
            description="合成作品，仅用于演示筛选、排序、快照和 CSV 导出。",
            published_at=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
            duration_seconds=Decimal("52.300"),
            canonical_url="https://example.invalid/demo-mock-content-001",
            cover_url=None,
            language="zh-CN",
            status="published",
            metadata_json={"demo": True, "is_mock": True, "generator_version": "1"},
            first_seen_at=DEMO_CAPTURED_AT,
            last_seen_at=DEMO_CAPTURED_AT,
            source_kind="mock",
            source_provider="mock_platform",
            fetched_at=DEMO_CAPTURED_AT,
            source_url=None,
            raw_payload_ref=None,
        )
        session.add(content)
        session.add(
            ContentSnapshot(
                id=stable_uuid(f"demo-content-snapshot:{workspace_id}"),
                content_item_id=content_id,
                captured_at=DEMO_CAPTURED_AT,
                view_count=1_250_000,
                like_count=105_000,
                comment_count=8_200,
                share_count=22_500,
                favorite_count=31_000,
                follower_gain=2_400,
                average_watch_time=Decimal("41.800"),
                completion_rate=Decimal("0.79800000"),
                search_traffic_rate=Decimal("0.18000000"),
                recommendation_traffic_rate=Decimal("0.69000000"),
                profile_traffic_rate=Decimal("0.13000000"),
                revenue=None,
                rpm=None,
                metadata_json={"demo": True, "is_mock": True},
                source_kind="mock",
                source_provider="mock_platform",
                fetched_at=DEMO_CAPTURED_AT,
                raw_payload_ref=None,
                created_at=DEMO_CAPTURED_AT,
            )
        )
        session.add(
            DerivedMetric(
                id=stable_uuid(f"demo-content-metric:{workspace_id}"),
                workspace_id=workspace_id,
                entity_type="content_item",
                entity_id=content_id,
                metric_key="view_growth_24h",
                window="24h",
                value=Decimal("410000"),
                calculated_at=DEMO_CAPTURED_AT,
                metadata_json={
                    "demo": True,
                    "is_mock": True,
                    "algorithm_version": "demo_fixture_v1",
                },
            )
        )
        created_contents = 1

    await session.commit()
    return {"accounts_created": created_accounts, "contents_created": created_contents}
