from typing import Protocol, TypeVar


class RegisteredProvider(Protocol):
    @property
    def key(self) -> str: ...


ProviderT = TypeVar("ProviderT", bound=RegisteredProvider)


class ProviderRegistry[ProviderT: RegisteredProvider]:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderT] = {}

    def register(self, provider: ProviderT) -> None:
        normalized_key = provider.key.strip().casefold()
        if not normalized_key:
            raise ValueError("provider key cannot be empty")
        if normalized_key in self._providers:
            raise ValueError(f"provider key is already registered: {normalized_key}")
        self._providers[normalized_key] = provider

    def replace(self, provider: ProviderT) -> None:
        """Register ``provider``, silently overriding any existing entry.

        Used by tests to swap a production provider for a real-shaped,
        test-local stand-in under the same key. Production code should keep
        using :meth:`register`, which fails loudly on duplicate keys.
        """
        normalized_key = provider.key.strip().casefold()
        if not normalized_key:
            raise ValueError("provider key cannot be empty")
        self._providers[normalized_key] = provider

    def get(self, key: str) -> ProviderT:
        normalized_key = key.strip().casefold()
        try:
            return self._providers[normalized_key]
        except KeyError as exc:
            raise LookupError(f"unknown provider: {normalized_key}") from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def values(self) -> tuple[ProviderT, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))
