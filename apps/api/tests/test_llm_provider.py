import pytest

from app.providers.llm.base import LLMMessage, LLMRequest
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.news.utils import ensure_public_llm_endpoint


def _request(model: str, parameters: dict[str, object]) -> LLMRequest:
    return LLMRequest(
        model=model,
        messages=(LLMMessage(role="user", content="hello"),),
        parameters=parameters,
        response_schema=None,
        timeout_seconds=90,
        idempotency_key="test-key",
    )


def test_reasoning_models_use_completion_budget_and_omit_sampling_parameters() -> None:
    payload = OpenAICompatibleProvider._generation_payload(
        _request(
            "gpt-5.6-terra",
            {"temperature": 0.2, "top_p": 0.8, "max_tokens": 8192},
        )
    )

    assert payload["max_completion_tokens"] == 8192
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "max_tokens" not in payload


def test_standard_models_keep_openai_compatible_sampling_parameters() -> None:
    payload = OpenAICompatibleProvider._generation_payload(
        _request(
            "gpt-4.1-mini",
            {"temperature": 0.2, "top_p": 0.8, "max_tokens": 4096},
        )
    )

    assert payload["temperature"] == 0.2
    assert payload["top_p"] == 0.8
    assert payload["max_tokens"] == 4096
    assert "max_completion_tokens" not in payload


def test_provider_normalizes_pasted_endpoint_and_supports_anonymous_local_mode() -> None:
    provider = OpenAICompatibleProvider(
        base_url="http://llm-gateway:3000/v1/chat/completions",
        api_key=None,
        timeout_seconds=10,
        max_attempts=1,
        provider_id="new-api",
        api_key_optional=True,
        internal_hosts=("llm-gateway",),
    )

    assert provider.base_url == "http://llm-gateway:3000/v1"
    assert provider.configured is True


def test_local_provider_uses_explicit_internal_host_allowlist() -> None:
    provider = OpenAICompatibleProvider(
        base_url="http://host.docker.internal:11434/v1",
        api_key=None,
        timeout_seconds=10,
        max_attempts=1,
        provider_id="ollama",
        api_key_optional=True,
        internal_hosts=("host.docker.internal",),
    )

    assert provider._is_internal_host() is True  # noqa: SLF001 - boundary contract


@pytest.mark.asyncio
async def test_unknown_llm_endpoint_keeps_dns_ssrf_check(monkeypatch) -> None:
    class PrivateResolver:
        async def getaddrinfo(self, *_args: object, **_kwargs: object) -> list[tuple]:
            return [(2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(
        "app.providers.news.utils.asyncio.get_running_loop", lambda: PrivateResolver()
    )
    with pytest.raises(ValueError, match="non-public"):
        await ensure_public_llm_endpoint("https://custom-provider.example/v1")
