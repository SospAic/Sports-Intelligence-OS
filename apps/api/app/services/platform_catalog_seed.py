import logging
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms import (
    BilibiliBrowserAdapter,
    DouyinAdapter,
    DouyinBrowserAdapter,
    DouyinYtDlpAdapter,
    TikTokAdapter,
    TikTokBrowserAdapter,
    TikTokYtDlpAdapter,
    YouTubeAdapter,
    YouTubeBrowserAdapter,
    YouTubeYtDlpAdapter,
)
from app.adapters.platforms.base import AdapterDescriptor
from app.models.monitoring import Platform

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
        YouTubeYtDlpAdapter,
        TikTokYtDlpAdapter,
        DouyinYtDlpAdapter,
    )
}

# (key, name, category, adapter_key)
# YouTube / TikTok / Douyin now default to the yt-dlp universal adapter
# (command-line extraction, no browser) with an automatic browser-simulation
# fallback. Browser scraping remains the mechanism for Bilibili and as the
# fallback everywhere else, so monitoring still works without API keys.
PLATFORM_CATALOG = (
    ("youtube", "YouTube", "video", "youtube_ytdlp"),
    ("tiktok", "TikTok", "video", "tiktok_ytdlp"),
    ("douyin", "抖音", "video", "douyin_ytdlp"),
    ("bilibili", "Bilibili", "video", "bilibili_browser"),
)


def stable_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sports-intelligence-os:{value}")


def _capabilities_from_descriptor(descriptor: AdapterDescriptor) -> dict[str, Any]:
    """Build the JSON-serialisable capabilities dict from an adapter descriptor."""
    reported = [
        capability.value for capability, supported in descriptor.capabilities.items() if supported
    ]
    return {
        "implementation_status": descriptor.implementation_status,
        "reported": reported,
        "private_analytics": "unavailable_not_fabricated",
    }


async def seed_platform_catalog(session: AsyncSession) -> tuple[int, int]:
    """Seed or update platform records from the catalog and adapter descriptors.

    Returns a ``(created, updated)`` count tuple so callers can report both
    new inserts and capability synchronisations. This is genuine platform
    metadata (not mock data) and must remain available for the system to
    register real accounts.
    """
    created = 0
    updated = 0
    for key, name, category, adapter_key in PLATFORM_CATALOG:
        # Resolve the descriptor by the *concrete* adapter key first (e.g.
        # "youtube_ytdlp"), falling back to the platform key. This is critical:
        # the legacy adapters also claim the bare platform keys ("youtube",
        # "tiktok", "douyin"), so resolving by platform key first would silently
        # pick the legacy adapter and undo the intended yt-dlp switch.
        descriptor = _ADAPTER_DESCRIPTORS.get(adapter_key) or _ADAPTER_DESCRIPTORS.get(key)
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
