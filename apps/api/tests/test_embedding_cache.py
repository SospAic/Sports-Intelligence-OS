"""Embedding cache: identical passages hit the backend only once."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.embedding import CachedEmbeddingService, EmbeddingError, EmbeddingService


def _cache_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://test",
        redis_url="redis://test",
        secret_key="test-only",
        embedding_backend="tei",
        embedding_model="BAAI/bge-m3",
        embedding_dimension=64,
        embedding_cache_enabled=True,
    )


@pytest.mark.asyncio
async def test_identical_passages_hit_backend_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    async def _fake_embed(self: EmbeddingService, texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        return [[float(i), 0.0, 0.0, 0.0] for i in range(len(texts))]

    # Patch the *base* method so the cache wrapper's super() call goes through it.
    monkeypatch.setattr(EmbeddingService, "embed_texts", _fake_embed)

    svc = CachedEmbeddingService(_cache_settings())
    out = await svc.embed_texts(["alpha", "beta", "alpha"])

    # "alpha" is embedded exactly once; the duplicate in the same batch is served
    # from the in-batch dedup, so the backend sees 2 distinct passages in 1 call.
    all_sent = [text for batch in calls for text in batch]
    assert all_sent.count("alpha") == 1
    assert all_sent.count("beta") == 1
    assert svc.cache_hits == 0
    assert svc.cache_misses == 2
    # Cached copy is byte-identical to the freshly computed one.
    assert out[0] == out[2]


@pytest.mark.asyncio
async def test_cache_is_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    async def _fake_embed(self: EmbeddingService, texts: list[str]) -> list[list[float]]:
        calls.append((self._model, list(texts)))
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(EmbeddingService, "embed_texts", _fake_embed)

    svc = CachedEmbeddingService(_cache_settings())
    svc._model = "model-A"
    await svc.embed_texts(["same"])
    svc._model = "model-B"
    await svc.embed_texts(["same"])

    # Same text, different model -> must not share a cached vector.
    assert len(calls) == 2
    assert {m for m, _ in calls} == {"model-A", "model-B"}


@pytest.mark.asyncio
async def test_disabled_backend_short_circuits() -> None:
    # Do NOT patch the base method here: the disabled path must reach the
    # real ``EmbeddingService.embed_texts``, which raises ``EmbeddingError``.
    settings = _cache_settings()
    settings.embedding_backend = "none"
    svc = CachedEmbeddingService(settings)
    with pytest.raises(EmbeddingError):
        await svc.embed_texts(["x"])
