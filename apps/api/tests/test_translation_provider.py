from __future__ import annotations

import json

import httpx
import pytest

from app.providers.translation.http import HttpTranslationProvider, TranslationUnavailable

_REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.mark.asyncio
async def test_http_translation_provider_accepts_libretranslate_batch_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/translate"
        assert json.loads(request.content)["q"] == ["Hello", "World"]
        return httpx.Response(200, json={"translatedText": ["你好", "世界"]})

    transport = httpx.MockTransport(handler)

    class MockClient:
        def __init__(self, *args, **kwargs):
            self._client = _REAL_ASYNC_CLIENT(transport=transport)

        async def __aenter__(self):
            await self._client.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self._client.__aexit__(*args)

        async def post(self, *args, **kwargs):
            return await self._client.post(*args, **kwargs)

    monkeypatch.setattr("app.providers.translation.http.httpx.AsyncClient", MockClient)
    provider = HttpTranslationProvider(
        base_url="http://translation:5000",
        api_key=None,
        timeout_seconds=30,
    )

    assert await provider.translate_segments(
        ["Hello", "World"], source_language="en", target_language="zh"
    ) == ["你好", "世界"]


@pytest.mark.asyncio
async def test_http_translation_provider_accepts_single_text_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"translatedText": "你好"})

    transport = httpx.MockTransport(handler)

    class MockClient:
        def __init__(self, *args, **kwargs):
            self._client = _REAL_ASYNC_CLIENT(transport=transport)

        async def __aenter__(self):
            await self._client.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self._client.__aexit__(*args)

        async def post(self, *args, **kwargs):
            return await self._client.post(*args, **kwargs)

    monkeypatch.setattr("app.providers.translation.http.httpx.AsyncClient", MockClient)
    provider = HttpTranslationProvider(
        base_url="http://translation:5000",
        api_key=None,
        timeout_seconds=30,
    )

    assert await provider.translate_segments(
        ["Hello"], source_language="en", target_language="zh"
    ) == ["你好"]


@pytest.mark.asyncio
async def test_http_translation_provider_normalizes_unknown_source_and_chinese_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["source"] == "auto"
        assert payload["target"] == "zh-Hans"
        return httpx.Response(200, json={"translatedText": ["你好"]})

    transport = httpx.MockTransport(handler)

    class MockClient:
        def __init__(self, *args, **kwargs):
            self._client = _REAL_ASYNC_CLIENT(transport=transport)

        async def __aenter__(self):
            await self._client.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self._client.__aexit__(*args)

        async def post(self, *args, **kwargs):
            return await self._client.post(*args, **kwargs)

    monkeypatch.setattr("app.providers.translation.http.httpx.AsyncClient", MockClient)
    provider = HttpTranslationProvider(
        base_url="http://translation:5000",
        api_key=None,
        timeout_seconds=30,
    )

    assert await provider.translate_segments(
        ["What happened?"], source_language="und-auto", target_language="zh"
    ) == ["你好"]


@pytest.mark.asyncio
async def test_http_translation_provider_includes_service_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Unsupported language pair")

    transport = httpx.MockTransport(handler)

    class MockClient:
        def __init__(self, *args, **kwargs):
            self._client = _REAL_ASYNC_CLIENT(transport=transport)

        async def __aenter__(self):
            await self._client.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self._client.__aexit__(*args)

        async def post(self, *args, **kwargs):
            return await self._client.post(*args, **kwargs)

    monkeypatch.setattr("app.providers.translation.http.httpx.AsyncClient", MockClient)
    provider = HttpTranslationProvider(
        base_url="http://translation:5000",
        api_key=None,
        timeout_seconds=30,
    )

    with pytest.raises(TranslationUnavailable, match="HTTP 400.*Unsupported language pair"):
        await provider.translate_segments(
            ["Hello"], source_language="en", target_language="zh"
        )
