"""HTTP adapter for a local LibreTranslate-compatible translation service.

The service can be backed by Argos, NLLB/CTranslate2, or another local model
server. The API never falls back to an LLM or estimated text when this provider
is unavailable.
"""

from __future__ import annotations

from typing import Any

import httpx

_LIBRETRANSLATE_LANGUAGE_ALIASES = {
    "zh": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-hans": "zh-Hans",
    "en-orig": "en",
}
_AUTO_SOURCE_CODES = {"", "auto", "und", "und-auto", "unknown", "unk"}


def _normalize_language(value: str | None, *, source: bool) -> str:
    """Convert product/platform language codes to LibreTranslate codes.

    Platform subtitles commonly use ``und-auto`` when the source language was
    not declared. LibreTranslate accepts ``auto`` for that case. Its Chinese
    model is exposed as ``zh-Hans`` rather than the product's shorter ``zh``
    value, so the provider owns that wire-format translation instead of
    leaking service-specific codes into the UI or media manifest.
    """

    cleaned = (value or "").strip().replace("_", "-").casefold()
    if source and cleaned in _AUTO_SOURCE_CODES:
        return "auto"
    if cleaned in _LIBRETRANSLATE_LANGUAGE_ALIASES:
        return _LIBRETRANSLATE_LANGUAGE_ALIASES[cleaned]
    if "-" in cleaned:
        base = cleaned.split("-", 1)[0]
        if base in _LIBRETRANSLATE_LANGUAGE_ALIASES:
            return _LIBRETRANSLATE_LANGUAGE_ALIASES[base]
        return base
    return cleaned


class TranslationUnavailable(RuntimeError):
    """Translation is not configured or the local service is unreachable."""


class HttpTranslationProvider:
    def __init__(self, *, base_url: str, api_key: str | None, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def translate_segments(
        self,
        texts: list[str],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[str]:
        if not texts:
            return []
        payload: dict[str, Any] = {
            "q": texts,
            "source": _normalize_language(source_language, source=True),
            "target": _normalize_language(target_language, source=False),
            "format": "text",
        }
        if self.api_key:
            payload["api_key"] = self.api_key
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/translate", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip().replace("\n", " ")[:300]
            suffix = f"：{detail}" if detail else ""
            raise TranslationUnavailable(
                f"本地翻译服务返回 HTTP {exc.response.status_code}{suffix}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise TranslationUnavailable(f"本地翻译服务请求失败：{str(exc)[:500]}") from exc

        if isinstance(body, dict) and isinstance(body.get("translatedText"), list):
            translated = [str(value) for value in body["translatedText"]]
        elif (
            isinstance(body, dict)
            and isinstance(body.get("translatedText"), str)
            and len(texts) == 1
        ):
            translated = [body["translatedText"]]
        elif isinstance(body, list):
            translated = [
                str(item.get("translatedText", ""))
                for item in body
                if isinstance(item, dict)
            ]
        else:
            raise TranslationUnavailable("本地翻译服务返回格式不受支持")
        if len(translated) != len(texts) or any(not value.strip() for value in translated):
            raise TranslationUnavailable("本地翻译服务未返回完整的分段结果")
        return translated
