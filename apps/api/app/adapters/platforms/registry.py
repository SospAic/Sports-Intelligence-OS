from app.adapters.platforms.base import PlatformAdapter
from app.adapters.platforms.mock import MockPlatformAdapter
from app.adapters.platforms.stubs import BilibiliAdapter, DouyinAdapter, TikTokAdapter
from app.adapters.platforms.youtube import YouTubeAdapter
from app.core.config import Settings
from app.providers.registry import ProviderRegistry


def build_platform_adapter_registry(
    settings: Settings | None = None,
) -> ProviderRegistry[PlatformAdapter]:
    registry: ProviderRegistry[PlatformAdapter] = ProviderRegistry()
    registry.register(
        YouTubeAdapter(
            timeout_seconds=(settings.platform_request_timeout_seconds if settings else 10.0),
            max_attempts=(settings.platform_request_max_attempts if settings else 3),
        )
    )
    registry.register(MockPlatformAdapter())
    registry.register(TikTokAdapter())
    registry.register(DouyinAdapter())
    registry.register(BilibiliAdapter())
    return registry
