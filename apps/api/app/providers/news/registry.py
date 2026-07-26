from app.core.config import Settings
from app.providers.news.base import NewsProvider
from app.providers.news.feed import AtomProvider, RSSProvider
from app.providers.news.json_feed import GenericJSONFeedProvider
from app.providers.news.manual import ManualNewsProvider
from app.providers.registry import ProviderRegistry


def build_news_provider_registry(
    settings: Settings | None = None,
) -> ProviderRegistry[NewsProvider]:
    timeout = settings.platform_request_timeout_seconds if settings else 15.0
    attempts = settings.platform_request_max_attempts if settings else 3
    registry: ProviderRegistry[NewsProvider] = ProviderRegistry()
    registry.register(RSSProvider(timeout_seconds=timeout, max_attempts=attempts))
    registry.register(AtomProvider(timeout_seconds=timeout, max_attempts=attempts))
    registry.register(GenericJSONFeedProvider(timeout_seconds=timeout, max_attempts=attempts))
    registry.register(ManualNewsProvider())
    return registry
