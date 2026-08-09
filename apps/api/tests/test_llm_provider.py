from app.providers.llm.base import LLMMessage, LLMRequest
from app.providers.llm.openai_compatible import OpenAICompatibleProvider


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
