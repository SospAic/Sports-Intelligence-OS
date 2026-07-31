from dataclasses import dataclass

import pytest

from app.providers.registry import ProviderRegistry


@dataclass(frozen=True)
class StubProvider:
    key: str


def test_registry_normalizes_keys_and_rejects_duplicates() -> None:
    registry: ProviderRegistry[StubProvider] = ProviderRegistry()
    provider = StubProvider(key=" Example ")
    registry.register(provider)

    assert registry.get("example") is provider
    assert registry.keys() == ("example",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubProvider(key="EXAMPLE"))


def test_registry_rejects_unknown_provider() -> None:
    registry: ProviderRegistry[StubProvider] = ProviderRegistry()
    with pytest.raises(LookupError, match="unknown provider"):
        registry.get("missing")
