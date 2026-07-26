from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    model: str
    messages: tuple[LLMMessage, ...]
    parameters: Mapping[str, Any]
    response_schema: Mapping[str, Any] | None
    timeout_seconds: float
    idempotency_key: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: Literal["reported", "estimated", "unavailable"]


@dataclass(frozen=True)
class LLMResponse:
    content: str | Mapping[str, Any]
    provider_request_id: str | None
    model: str
    finish_reason: str
    usage: LLMUsage
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMHealth:
    status: Literal["ok", "degraded", "unavailable"]
    detail: str


class LLMProviderError(RuntimeError):
    code = "llm_provider_error"
    retryable = False


class LLMProviderConfigurationError(LLMProviderError):
    code = "llm_provider_configuration_error"


class LLMProviderAuthenticationError(LLMProviderError):
    code = "llm_provider_authentication_error"


class LLMProviderRateLimitError(LLMProviderError):
    code = "llm_provider_rate_limited"
    retryable = True


class LLMProviderTransientError(LLMProviderError):
    code = "llm_provider_transient_error"
    retryable = True


class LLMProviderContractError(LLMProviderError):
    code = "llm_provider_contract_error"


class LLMProvider(ABC):
    key: str
    name: str
    is_mock: bool = False
    supports_streaming: bool = False

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def validate_config(self, config: Mapping[str, Any]) -> None: ...

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        if False:
            yield ""

    @abstractmethod
    async def estimate_cost(self, usage: LLMUsage, config: Mapping[str, Any]) -> Decimal | None: ...

    @abstractmethod
    async def health_check(self) -> LLMHealth: ...
