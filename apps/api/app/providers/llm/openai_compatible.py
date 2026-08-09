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
from app.providers.news.utils import ensure_public_endpoint, validate_source_url


class OpenAICompatibleProvider(LLMProvider):
    key = "openai_compatible"
    name = "OpenAI 兼容接口"
    supports_streaming = True

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        timeout_seconds: float,
        max_attempts: int,
        organization: str | None = None,
        project: str | None = None,
        custom_headers: Mapping[str, str] | None = None,
        internal_hosts: tuple[str, ...] = (),
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.organization = organization
        self.project = project
        self.custom_headers = dict(custom_headers or {})
        self._internal_hosts = frozenset(h.casefold() for h in internal_hosts)

    def _is_internal_host(self) -> bool:
        """Return True if base_url targets an allowlisted Docker-internal host."""
        if not self.base_url or not self._internal_hosts:
            return False
        from urllib.parse import urlsplit

        host = (urlsplit(self.base_url).hostname or "").casefold()
        return host in self._internal_hosts

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._api_key)

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """Return whether the model uses the modern reasoning parameter contract.

        OpenAI-compatible gateways commonly expose GPT-5 and o-series models
        through Chat Completions, but reject sampling parameters such as
        ``temperature`` and use ``max_completion_tokens`` instead.  Keep this
        deliberately narrow so ordinary third-party models retain the legacy
        contract.
        """
        normalized = model.strip().casefold()
        return normalized.startswith(("gpt-5", "o1", "o3", "o4"))

    @classmethod
    def _generation_payload(cls, request: LLMRequest, *, stream: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if cls._is_reasoning_model(request.model):
            if "max_completion_tokens" in request.parameters:
                payload["max_completion_tokens"] = request.parameters["max_completion_tokens"]
            elif "max_tokens" in request.parameters:
                payload["max_completion_tokens"] = request.parameters["max_tokens"]
            if "reasoning_effort" in request.parameters:
                payload["reasoning_effort"] = request.parameters["reasoning_effort"]
        else:
            payload["temperature"] = float(request.parameters.get("temperature", 0.4))
            for key in ("top_p", "max_tokens", "max_completion_tokens"):
                if key in request.parameters:
                    payload[key] = request.parameters[key]
        if stream:
            payload["stream"] = True
        return payload

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        if not self.configured:
            raise LLMProviderConfigurationError(
                "OpenAI compatible provider requires backend base URL and API key"
            )
        if not self.base_url:
            raise LLMProviderConfigurationError("LLM base URL is required")
        if self._is_internal_host():
            return
        try:
            validate_source_url(self.base_url, allow_secret_query=False)
        except ValueError as exc:
            raise LLMProviderConfigurationError(str(exc)) from exc

    async def generate(self, request: LLMRequest) -> LLMResponse:
        await self.validate_config(request.parameters)
        payload = self._generation_payload(request)
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            **self.custom_headers,
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": request.idempotency_key,
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        if not self._is_internal_host():
            try:
                await ensure_public_endpoint(str(self.base_url), allow_secret_query=False)
            except ValueError as exc:
                raise LLMProviderConfigurationError(str(exc)) from exc
            except OSError as exc:
                raise LLMProviderTransientError(str(exc)) from exc
        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=False
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.post(
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
        await self.validate_config(request.parameters)
        payload = self._generation_payload(request, stream=True)
        # Streaming is incompatible with JSON response format; omit response_format.
        headers = {
            **self.custom_headers,
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": request.idempotency_key,
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        if not self._is_internal_host():
            try:
                await ensure_public_endpoint(str(self.base_url), allow_secret_query=False)
            except ValueError as exc:
                raise LLMProviderConfigurationError(str(exc)) from exc
            except OSError as exc:
                raise LLMProviderTransientError(str(exc)) from exc
        assert self.base_url is not None
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(request.timeout_seconds, read=300.0),
            follow_redirects=False,
        ) as client:
            response: httpx.Response | None = None
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.send(
                        client.build_request("POST", url, headers=headers, json=payload),
                        stream=True,
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == self.max_attempts:
                        raise LLMProviderTransientError(
                            "LLM streaming request failed after retries"
                        ) from exc
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                    continue
                if response.status_code == 429:
                    await response.aclose()
                    if attempt == self.max_attempts:
                        raise LLMProviderRateLimitError("LLM rate limit exceeded")
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                    continue
                if response.status_code in {401, 403}:
                    await response.aclose()
                    raise LLMProviderAuthenticationError("LLM credentials were rejected")
                if response.status_code >= 500:
                    await response.aclose()
                    if attempt == self.max_attempts:
                        raise LLMProviderTransientError("LLM service is unavailable")
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                    continue
                if response.status_code >= 400:
                    await response.aclose()
                    raise LLMProviderContractError(
                        f"LLM streaming request rejected with status {response.status_code}"
                    )
                break
            if response is None:
                raise LLMProviderTransientError("LLM streaming request did not return")
            try:
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith(":"):
                        # SSE comment, skip
                        continue
                    if line.startswith("data:"):
                        data_str = line[len("data:") :].strip()
                    else:
                        continue
                    if data_str == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices")
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    token = delta.get("content")
                    if token:
                        yield str(token)
            finally:
                await response.aclose()

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

    async def test_connection(self) -> LLMHealth:
        await self.validate_config({})
        assert self.base_url is not None
        if not self._is_internal_host():
            try:
                await ensure_public_endpoint(self.base_url, allow_secret_query=False)
            except ValueError as exc:
                raise LLMProviderConfigurationError(str(exc)) from exc
            except OSError as exc:
                raise LLMProviderTransientError(str(exc)) from exc
        headers = {**self.custom_headers, "Authorization": f"Bearer {self._api_key}"}
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.get(f"{self.base_url}/models", headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LLMProviderTransientError("LLM connection test failed") from exc
        if response.status_code in {401, 403}:
            raise LLMProviderAuthenticationError("LLM credentials were rejected")
        if response.status_code >= 500:
            raise LLMProviderTransientError("LLM service is unavailable")
        if response.status_code >= 400:
            raise LLMProviderContractError(
                f"LLM connection test was rejected with status {response.status_code}"
            )
        return LLMHealth(status="ok", detail="Authentication and /models endpoint verified")

    async def list_models(self) -> list[dict[str, str | None]]:
        await self.validate_config({})
        assert self.base_url is not None
        if not self._is_internal_host():
            try:
                await ensure_public_endpoint(self.base_url, allow_secret_query=False)
            except ValueError as exc:
                raise LLMProviderConfigurationError(str(exc)) from exc
            except OSError as exc:
                raise LLMProviderTransientError(str(exc)) from exc
        headers = {**self.custom_headers, "Authorization": f"Bearer {self._api_key}"}
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.get(f"{self.base_url}/models", headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LLMProviderTransientError("LLM model list request failed") from exc
        if response.status_code in {401, 403}:
            raise LLMProviderAuthenticationError("LLM credentials were rejected")
        if response.status_code >= 500:
            raise LLMProviderTransientError("LLM service is unavailable")
        if response.status_code >= 400:
            raise LLMProviderContractError(
                f"LLM model list request was rejected with status {response.status_code}"
            )
        try:
            payload = response.json()
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            return [
                {
                    "id": str(row["id"]),
                    "name": str(row.get("name") or row["id"]),
                    "owned_by": str(row["owned_by"]) if row.get("owned_by") else None,
                }
                for row in rows
                if isinstance(row, dict) and row.get("id")
            ]
        except (TypeError, ValueError, KeyError) as exc:
            raise LLMProviderContractError("LLM model list response was invalid") from exc

    async def aclose(self) -> None:
        return None
