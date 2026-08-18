"""Thin helper for calling the workspace LLM to produce structured JSON.

Both the derivative-topic engine and the smart-search analysis need a single
LLM call that returns a JSON object. This module centralises provider
resolution (mirrors :mod:`app.services.generation`) and robust JSON extraction
so the callers can stay focused on prompt design and persistence.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.providers.llm.base import LLMMessage, LLMProvider, LLMRequest
from app.providers.registry import ProviderRegistry
from app.services.settings import SettingsService


class LLMUnavailableError(RuntimeError):
    """Raised when the workspace LLM is not configured or returns no JSON."""

    code = "llm_unavailable"


_JSON_OBJECT = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


async def call_json_llm(
    session: AsyncSession,
    llm_providers: ProviderRegistry[LLMProvider],
    settings: Settings | None,
    workspace_id: uuid.UUID,
    *,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float = 60.0,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Resolve the workspace's OpenAI-compatible provider and ask for JSON.

    Returns the parsed dict. Raises :class:`LLMUnavailableError` when the
    provider is unconfigured or the response cannot be parsed as JSON, so
    callers can degrade gracefully instead of 500-ing.
    """
    svc = SettingsService(session, settings or get_settings(), llm_providers)
    provider = await svc.resolve_llm_provider(workspace_id, "openai_compatible")
    if not provider.configured:
        raise LLMUnavailableError("LLM 未配置，请在「设置 → LLM」中配置 OpenAI 兼容模型")

    model, params, _, _ = await svc.effective_llm_defaults(workspace_id)
    parameters: dict[str, Any] = {
        "temperature": float(params.get("temperature", 0.4)),
        "top_p": float(params.get("top_p", 0.9)),
    }
    if max_tokens is not None:
        parameters["max_tokens"] = max_tokens

    request = LLMRequest(
        model=model,
        messages=(
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ),
        parameters=parameters,
        response_schema=None,
        timeout_seconds=timeout_seconds,
        idempotency_key=f"hotspot-{uuid.uuid4().hex}",
    )
    response = await provider.generate(request)
    content = response.content
    if isinstance(content, Mapping):
        return dict(content)
    text = str(content)
    match = _JSON_OBJECT.search(text)
    if not match:
        raise LLMUnavailableError("LLM 未返回可解析的 JSON 结构")
    try:
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise LLMUnavailableError("LLM 返回的 JSON 顶层必须是对象")
        return {str(key): value for key, value in parsed.items()}
    except json.JSONDecodeError as exc:
        raise LLMUnavailableError(f"LLM 返回的 JSON 解析失败: {exc}") from exc
