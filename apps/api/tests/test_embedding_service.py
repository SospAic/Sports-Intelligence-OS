"""EmbeddingService contract against stubbed local backends.

No real model is started: httpx is intercepted with MockTransport, so these run
in the default CI slice. What they lock down is the failure behaviour — a wrong
dimension or a partial batch must raise loudly rather than silently poisoning
the vector index.
"""

import json

import httpx
import pytest

from app.core.config import Settings
from app.services import embedding as embedding_module
from app.services.embedding import EmbeddingError, EmbeddingService, build_embedding_service


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Keep the retry test fast; the backoff itself is not what we assert on."""

    monkeypatch.setattr(embedding_module, "_RETRY_BACKOFF_SECONDS", 0.0)


#: 配置约束 embedding_dimension >= 64，所以测试也必须用一个合法宽度。
_DIM = 64


def _settings(**overrides) -> Settings:
    base = {
        "embedding_backend": "tei",
        "embedding_base_url": "http://embeddings:80",
        "embedding_model": "BAAI/bge-m3",
        "embedding_dimension": _DIM,
        "embedding_batch_size": 2,
    }
    base.update(overrides)
    return Settings(**base)


class _StubService(EmbeddingService):
    """EmbeddingService whose httpx client is backed by a MockTransport."""

    def __init__(self, settings: Settings, handler) -> None:
        super().__init__(settings)
        self._handler = handler

    async def embed_texts(self, texts):  # type: ignore[override]
        if not self.enabled:
            raise EmbeddingError("embedding backend is disabled")
        if not texts:
            return []
        for index, text in enumerate(texts):
            if not text or not text.strip():
                raise EmbeddingError(f"texts[{index}] is empty; refusing to embed blank input")
        transport = httpx.MockTransport(self._handler)
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(transport=transport, timeout=1.0) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = list(texts[start : start + self._batch_size])
                vectors.extend(await self._embed_batch(client, batch))
        return vectors


# --- enablement ------------------------------------------------------------


def test_service_is_disabled_when_backend_is_none():
    service = build_embedding_service(_settings(embedding_backend="none"))
    assert service.enabled is False


async def test_disabled_service_raises_instead_of_returning_empty():
    service = build_embedding_service(_settings(embedding_backend="none"))
    with pytest.raises(EmbeddingError, match="disabled"):
        await service.embed_texts(["排球"])


def test_service_exposes_model_and_dimension():
    service = build_embedding_service(_settings())
    assert service.model == "BAAI/bge-m3"
    assert service.dimension == _DIM
    assert service.backend == "tei"


# --- OpenAI-compatible (tei) backend ---------------------------------------


async def test_openai_compatible_backend_batches_and_preserves_order():
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        body = json.loads(request.content)
        seen.append(body["input"])
        data = [
            {"index": i, "embedding": [float(len(text))] * _DIM}
            for i, text in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": data})

    service = _StubService(_settings(), handler)
    vectors = await service.embed_texts(["ab", "abcd", "abcdef"])

    # batch_size=2 → 两次请求，顺序必须与输入一致。
    assert seen == [["ab", "abcd"], ["abcdef"]]
    assert [vector[0] for vector in vectors] == [2.0, 4.0, 6.0]


async def test_openai_compatible_backend_reorders_by_index():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [2.0] * _DIM},
                    {"index": 0, "embedding": [1.0] * _DIM},
                ]
            },
        )

    service = _StubService(_settings(), handler)
    vectors = await service.embed_texts(["first", "second"])
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0


async def test_api_key_is_sent_as_bearer_token():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * _DIM}]})

    service = _StubService(_settings(embedding_api_key="secret-token"), handler)
    await service.embed_texts(["x"])
    assert captured["auth"] == "Bearer secret-token"


# --- ollama backend --------------------------------------------------------


async def test_ollama_backend_uses_native_embed_endpoint():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"embeddings": [[0.1] * _DIM]})

    service = _StubService(_settings(embedding_backend="ollama"), handler)
    vectors = await service.embed_texts(["排球"])
    # /api/embed 支持批量；已废弃的 /api/embeddings 一次只能一条，不能用。
    assert captured["path"] == "/api/embed"
    assert vectors == [[0.1] * _DIM]


# --- failure modes ---------------------------------------------------------


async def test_dimension_mismatch_is_rejected():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 768}]})

    service = _StubService(_settings(), handler)
    with pytest.raises(EmbeddingError, match="768-dimensional"):
        await service.embed_texts(["x"])


async def test_partial_batch_response_is_rejected():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * _DIM}]})

    service = _StubService(_settings(), handler)
    with pytest.raises(EmbeddingError, match="1 vectors for 2 inputs"):
        await service.embed_texts(["a", "b"])


async def test_http_error_is_retried_then_surfaced():
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, text="model is loading")

    service = _StubService(_settings(), handler)
    with pytest.raises(EmbeddingError, match="failed after 3 attempts"):
        await service.embed_texts(["x"])
    assert calls["count"] == 3


async def test_blank_input_is_rejected_before_any_request():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("backend must not be called for blank input")

    service = _StubService(_settings(), handler)
    with pytest.raises(EmbeddingError, match="texts\\[1\\] is empty"):
        await service.embed_texts(["ok", "   "])


async def test_empty_input_short_circuits():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("backend must not be called for an empty list")

    service = _StubService(_settings(), handler)
    assert await service.embed_texts([]) == []
