from app.core.config import Settings
from app.providers.llm.base import LLMProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import ProviderRegistry


def build_llm_provider_registry(settings: Settings) -> ProviderRegistry[LLMProvider]:
    registry: ProviderRegistry[LLMProvider] = ProviderRegistry()
    registry.register(MockLLMProvider())
    registry.register(
        OpenAICompatibleProvider(
            base_url=settings.llm_openai_compatible_base_url,
            api_key=(
                settings.llm_openai_compatible_api_key.get_secret_value()
                if settings.llm_openai_compatible_api_key
                else None
            ),
            timeout_seconds=settings.llm_request_timeout_seconds,
            max_attempts=settings.llm_request_max_attempts,
        )
    )
    return registry
