from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from typing import Any

import httpx

from app.providers.llm.base import (
    LLMHealth,
    LLMProvider,
    LLMProviderAuthenticationError,
    LLMProviderConfigurationError,
    LLMProviderContractError,
    LLMProviderRateLimitError,
    LLMProviderTransientError,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)


class OpenAICompatibleProvider(LLMProvider):
    key = "openai_compatible"
    name = "OpenAI 兼容接口"
    supports_streaming = False

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        timeout_seconds: float,
        max_attempts: int,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self._client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._api_key)

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        if not self.configured:
            raise LLMProviderConfigurationError(
                "OpenAI compatible provider requires backend base URL and API key"
            )
        if not self.base_url or not self.base_url.startswith(("https://", "http://")):
            raise LLMProviderConfigurationError("LLM base URL must use HTTP or HTTPS")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        await self.validate_config(request.parameters)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
            "temperature": float(request.parameters.get("temperature", 0.4)),
        }
        for key in ("top_p", "max_tokens"):
            if key in request.parameters:
                payload[key] = request.parameters[key]
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": request.idempotency_key,
        }
        response: httpx.Response | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=request.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self.max_attempts:
                    raise LLMProviderTransientError("LLM request failed after retries") from exc
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue
            if response.status_code == 429:
                if attempt == self.max_attempts:
                    raise LLMProviderRateLimitError("LLM rate limit exceeded")
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue
            if response.status_code in {401, 403}:
                raise LLMProviderAuthenticationError("LLM credentials were rejected")
            if response.status_code >= 500:
                if attempt == self.max_attempts:
                    raise LLMProviderTransientError("LLM service is unavailable")
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue
            if response.status_code >= 400:
                raise LLMProviderContractError(
                    f"LLM request was rejected with status {response.status_code}"
                )
            break
        if response is None:
            raise LLMProviderTransientError("LLM request did not return a response")
        try:
            body = response.json()
            choice = body["choices"][0]
            raw_content = choice["message"]["content"]
            usage_body = body.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderContractError("LLM response did not match the chat contract") from exc
        content: str | Mapping[str, Any] = str(raw_content)
        if request.response_schema is not None:
            try:
                parsed = json.loads(str(raw_content))
            except json.JSONDecodeError as exc:
                raise LLMProviderContractError(
                    "LLM structured response was not valid JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise LLMProviderContractError("LLM structured response must be a JSON object")
            content = parsed
        usage = LLMUsage(
            input_tokens=int(usage_body.get("prompt_tokens", 0)),
            output_tokens=int(usage_body.get("completion_tokens", 0)),
            total_tokens=int(usage_body.get("total_tokens", 0)),
            source="reported" if usage_body else "unavailable",
        )
        return LLMResponse(
            content=content,
            provider_request_id=response.headers.get("x-request-id") or body.get("id"),
            model=str(body.get("model") or request.model),
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            usage=usage,
            provider_metadata={"response_format": "json" if request.response_schema else "text"},
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        raise LLMProviderConfigurationError(
            "Streaming is not enabled for the first-phase OpenAI compatible provider"
        )
        if False:
            yield ""

    async def estimate_cost(self, usage: LLMUsage, config: Mapping[str, Any]) -> Decimal | None:
        if "input_cost_per_million" not in config or "output_cost_per_million" not in config:
            return None
        input_rate = Decimal(str(config["input_cost_per_million"]))
        output_rate = Decimal(str(config["output_cost_per_million"]))
        return (
            Decimal(usage.input_tokens) * input_rate + Decimal(usage.output_tokens) * output_rate
        ) / Decimal(1_000_000)

    async def health_check(self) -> LLMHealth:
        if not self.configured:
            return LLMHealth(
                status="unavailable", detail="Backend base URL or API key is not configured"
            )
        return LLMHealth(status="ok", detail="Configuration is present; no billable call was made")

    async def aclose(self) -> None:
        await self._client.aclose()
