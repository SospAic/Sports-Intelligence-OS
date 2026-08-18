"""Client for a self-hosted embedding backend.

为什么不用 LLM
--------------
检索本身是"把文本映射成向量再比余弦距离"，不需要生成模型。用本地 embedding
服务（默认 BGE-M3）替代 LLM 调用带来三个确定性收益：单次查询成本为零、结果
可复现、语料不出内网。LLM 只在用户明确要求"总结这些召回结果"时才被调用，
属于可选后置步骤，不在检索关键路径上。

支持的后端
----------
``tei``
    任何暴露 OpenAI 兼容 ``/v1/embeddings`` 的服务：HuggingFace Text Embeddings
    Inference、vLLM、Infinity、本地 llm-gateway 等。
``ollama``
    Ollama 的 ``/api/embed``（注意不是已废弃的 ``/api/embeddings``，后者一次
    只能处理一条文本）。
``none``
    不生成向量。``enabled`` 为 False，调用方应当降级而不是报错。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.text_chunking import sha256_text

logger = logging.getLogger(__name__)

#: 网络抖动重试次数（含首次）。embedding 服务通常与 API 同机，失败多半是
#: 模型仍在加载，短暂退避即可恢复。
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.5


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend is unreachable or returns bad data."""


class EmbeddingService:
    """Turns text into vectors using a locally deployed model."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._backend = self._settings.embedding_backend
        self._base_url = self._settings.embedding_base_url.rstrip("/")
        self._model = self._settings.embedding_model
        self._dimension = self._settings.embedding_dimension
        self._batch_size = self._settings.embedding_batch_size
        self._timeout = self._settings.embedding_request_timeout_seconds
        api_key = self._settings.embedding_api_key
        self._api_key = api_key.get_secret_value() if api_key is not None else None

    @property
    def enabled(self) -> bool:
        return self._backend != "none"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def backend(self) -> str:
        return self._backend

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of passages, preserving input order.

        空字符串会被拒绝而不是静默跳过——调用方如果把空文本混进来，说明分块
        逻辑有问题，静默处理只会让索引里出现无意义的零向量。
        """

        if not self.enabled:
            raise EmbeddingError(
                "embedding backend is disabled; set SIO_EMBEDDING_BACKEND to 'tei' or 'ollama'"
            )
        if not texts:
            return []
        for index, text in enumerate(texts):
            if not text or not text.strip():
                raise EmbeddingError(f"texts[{index}] is empty; refusing to embed blank input")

        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = list(texts[start : start + self._batch_size])
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single search query.

        BGE-M3 是 instruction-free 模型，query 与 passage 用同一编码方式；
        换成 e5 系列时需要在这里补 ``query: `` 前缀。
        """

        vectors = await self.embed_texts([text])
        return vectors[0]

    async def _embed_batch(
        self, client: httpx.AsyncClient, batch: Sequence[str]
    ) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                payload = await self._post(client, batch)
            except (httpx.HTTPError, EmbeddingError) as exc:
                last_error = exc
                if attempt == _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue
            return self._validate(payload, expected=len(batch))
        raise EmbeddingError(
            f"embedding backend '{self._backend}' at {self._base_url} failed after "
            f"{_MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    async def _post(self, client: httpx.AsyncClient, batch: Sequence[str]) -> list[list[float]]:
        if self._backend == "ollama":
            url = f"{self._base_url}/api/embed"
            body: dict[str, Any] = {"model": self._model, "input": list(batch)}
            headers: dict[str, str] = {}
        else:
            url = f"{self._base_url}/v1/embeddings"
            body = {"model": self._model, "input": list(batch)}
            headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        response = await client.post(url, json=body, headers=headers)
        if response.status_code >= 400:
            raise EmbeddingError(
                f"embedding backend returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
        except ValueError as exc:  # pragma: no cover - malformed backend
            raise EmbeddingError("embedding backend returned non-JSON payload") from exc
        return self._extract(data)

    def _extract(self, data: Any) -> list[list[float]]:
        if not isinstance(data, dict):
            raise EmbeddingError("embedding response must be a JSON object")
        if self._backend == "ollama":
            raw = data.get("embeddings")
        else:
            entries = data.get("data")
            if not isinstance(entries, list):
                raise EmbeddingError("OpenAI-compatible response is missing 'data'")
            # 兼容乱序返回：有 index 字段就按它排序。
            try:
                entries = sorted(entries, key=lambda item: int(item.get("index", 0)))
            except (TypeError, ValueError):
                pass
            raw = [entry.get("embedding") for entry in entries if isinstance(entry, dict)]
        if not isinstance(raw, list):
            raise EmbeddingError("embedding response did not contain a list of vectors")
        return [[float(value) for value in vector] for vector in raw]

    def _validate(self, vectors: list[list[float]], *, expected: int) -> list[list[float]]:
        if len(vectors) != expected:
            raise EmbeddingError(
                f"embedding backend returned {len(vectors)} vectors for {expected} inputs"
            )
        for vector in vectors:
            if len(vector) != self._dimension:
                raise EmbeddingError(
                    f"model '{self._model}' returned {len(vector)}-dimensional vectors but "
                    f"SIO_EMBEDDING_DIMENSION is {self._dimension}; the database column and "
                    "the deployed model must agree"
                )
        return vectors


class CachedEmbeddingService(EmbeddingService):
    """``EmbeddingService`` with an in-process LRU cache keyed by ``(model, text)``.

    Re-indexing the same caption / description / subtitle block across runs would
    otherwise re-hit the backend every time. Identical passages collapse to one
    backend call; the cache is bounded so a long backfill cannot exhaust memory.
    """

    def __init__(self, settings: Settings | None = None, max_entries: int = 20000) -> None:
        super().__init__(settings)
        self._cache: dict[str, list[float]] = {}
        self._cache_max = max(1, int(max_entries))
        self.cache_hits = 0
        self.cache_misses = 0

    def _key(self, text: str) -> str:
        return sha256_text(f"{self._model}\0{text}")

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.enabled:
            # Short-circuit exactly like the base class (raises EmbeddingError).
            return await super().embed_texts(texts)

        results: list[list[float] | None] = [None] * len(texts)
        # Deduplicate within the batch: the same passage appearing twice in one
        # call must still hit the backend only once. We remember which miss
        # slot each input position resolves to and fill them all afterwards.
        seen_keys: dict[str, int] = {}
        miss_texts: list[str] = []
        index_to_slot: list[int] = []
        for index, text in enumerate(texts):
            key = self._key(text)
            cached = self._cache.get(key)
            if cached is not None:
                results[index] = cached
                self.cache_hits += 1
                index_to_slot.append(-1)
                continue
            slot = seen_keys.get(key)
            if slot is None:
                slot = len(miss_texts)
                seen_keys[key] = slot
                miss_texts.append(text)
                self.cache_misses += 1
            index_to_slot.append(slot)

        if miss_texts:
            computed = await super().embed_texts(miss_texts)
            for text, vector in zip(miss_texts, computed, strict=True):
                self._cache[self._key(text)] = vector
            for index, slot in enumerate(index_to_slot):
                if slot >= 0:
                    results[index] = computed[slot]
            # Crude LRU eviction: when over budget, drop the oldest half.
            if len(self._cache) > self._cache_max:
                excess = len(self._cache) - self._cache_max
                for stale in list(self._cache)[: max(excess, self._cache_max // 2)]:
                    self._cache.pop(stale, None)

        return [row for row in results if row is not None]


def build_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    """Factory kept separate so tests can swap in a stub.

    Wraps the service in an in-process cache unless ``embedding_cache_enabled``
    is off, so both ``ContentIndexingService`` and ``SemanticSearchService``
    (which receive the embedder via dependency injection) benefit for free.
    """

    resolved = settings or get_settings()
    if resolved.embedding_cache_enabled and resolved.embedding_backend != "none":
        return CachedEmbeddingService(resolved, max_entries=resolved.embedding_cache_max_entries)
    return EmbeddingService(resolved)
