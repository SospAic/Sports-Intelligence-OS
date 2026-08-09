"""Hybrid retrieval over locally embedded content — no LLM in the hot path.

融合策略
--------
向量召回擅长"说法不同但意思一样"（*逆转绝杀* ↔ *最后时刻反超*），关键词召回
擅长精确名词（人名、队名、比分）。两者的分数不可直接比较（余弦距离 vs 出现
次数），所以用 **RRF（Reciprocal Rank Fusion）** 只按名次融合：

    score = Σ  weight / (K + rank)

RRF 的好处是无需归一化、对异常分值鲁棒，是 BM25+向量混合检索的业界默认做法。
``K = 60`` 是原论文给出的经验值。

聚合到内容
----------
命中的是"块"，但用户要看的是"视频"。同一视频的多个块只保留分数最高的作为
``best_chunk``（附带 ``start_ms`` 可直接 seek），其余按分数排在 ``chunks`` 里。

重排（可选，默认关闭）
----------------------
RRF 只看名次，丢掉了"到底有多像"。开启 ``SIO_RERANK_ENABLED`` 后，融合列表的
前 ``rerank_top_n`` 条会再过一遍交叉特征打分：归一化向量相似度、关键词命中密度、
新鲜度、来源质量。仍然不引入任何模型依赖——纯算术，毫秒级。关闭时整条链路与
重排上线前逐字节一致。
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Float, String, bindparam, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.embedding import ContentEmbedding, Vector, encode_vector
from app.models.monitoring import ContentItem
from app.services.embedding import EmbeddingError, EmbeddingService, build_embedding_service

#: RRF 平滑常数。越大越"平"，头部名次的优势越小。
RRF_K = 60

#: 两路召回的权重。向量略高：它是这套方案相对旧的 ILIKE 搜索的增量价值所在。
VECTOR_WEIGHT = 1.0
KEYWORD_WEIGHT = 0.8

#: 单条内容最多回传几个片段。
MAX_CHUNKS_PER_HIT = 3

#: 关键词最多拆几个词，防止超长查询拼出巨大的 SQL。
MAX_KEYWORD_TERMS = 8

#: 重排的四路特征权重，和为 1，所以 rerank_score 天然落在 [0, 1]。
RERANK_VECTOR_WEIGHT = 0.45
RERANK_KEYWORD_WEIGHT = 0.30
RERANK_RECENCY_WEIGHT = 0.15
RERANK_SOURCE_WEIGHT = 0.10

#: 关键词特征内部：命中词数占比 vs 命中字符密度。前者防止长文本被密度稀释，
#: 后者防止"一句话里塞满查询词"的短块被低估。
KEYWORD_COVERAGE_WEIGHT = 0.7
KEYWORD_DENSITY_WEIGHT = 0.3

#: 新鲜度半衰期（天）。体育内容既看时效也吃存档，90 天是折中：三个月前的素材
#: 仍保留一半权重，一年前的降到约 0.06。
RECENCY_HALF_LIFE_DAYS = 90.0

#: 没有发布时间时给中性分，避免把"平台没吐出时间"当成"很旧"来惩罚。
RECENCY_UNKNOWN_SCORE = 0.5

#: 来源质量：基础分 + 三项加成，上限 1.0。
SOURCE_QUALITY_BASE = 0.4
#: 平台直采比人工导入更可信（导入的元数据经常缺字段）。
SOURCE_QUALITY_LIVE_BONUS = 0.2
#: 已下架 / 私密的内容命中了也没法用。
SOURCE_QUALITY_PUBLISHED_BONUS = 0.2
#: 字幕/转写是"片子里真的说了这句话"，比标题简介的强度高一档。
SOURCE_QUALITY_SPOKEN_BONUS = 0.2
SPOKEN_CHUNK_KINDS = frozenset({"subtitle", "transcript"})


class SemanticSearchDisabledError(RuntimeError):
    """Raised when the deployment has not enabled local semantic search."""


@dataclass(slots=True)
class RerankFeatures:
    """The cross-features behind one reranked chunk, kept for explainability."""

    vector: float
    keyword: float
    recency: float
    source: float
    score: float


@dataclass(slots=True)
class ScoreBreakdown:
    """Per-chunk scoring trace, only built when the caller asks for ``debug``."""

    vector_score: float | None
    keyword_score: float
    rrf_score: float
    rerank_score: float | None
    explanation: str


@dataclass(slots=True)
class ChunkHit:
    """One retrieved chunk with its fused score."""

    embedding_id: UUID
    content_item_id: UUID
    chunk_kind: str
    chunk_index: int
    text: str
    start_ms: int | None
    end_ms: int | None
    source_ref: str | None
    distance: float | None = None
    score: float = 0.0
    matched_by: list[str] = field(default_factory=list)
    #: 融合分。``score`` 会被重排覆盖，这里留一份原始名次分给解释用。
    rrf_score: float = 0.0
    #: 仅在重排真正跑过这一条时非空。
    rerank: RerankFeatures | None = None
    breakdown: ScoreBreakdown | None = None


@dataclass(slots=True)
class ItemHit:
    item: ContentItem
    score: float
    chunks: list[ChunkHit]


def tokenise_query(query: str, *, limit: int = MAX_KEYWORD_TERMS) -> list[str]:
    """Split a query into keyword terms.

    中文不分词，所以对没有空格的查询直接整串匹配；有空格时按空格拆，让
    "刘翔 跨栏" 这类查询变成 AND 条件。
    """

    terms = [term for term in query.split() if term.strip()]
    if not terms:
        return []
    return terms[:limit]


def vector_similarity(distance: float | None) -> float | None:
    """Cosine distance → similarity in ``[0, 1]``.

    pgvector 的 ``<=>`` 返回 ``1 - cos``，取值 0（同向）到 2（反向）。负相关的块
    对排序没有意义，直接截到 0。纯关键词命中的块没有距离，返回 ``None``。
    """

    if distance is None:
        return None
    return max(0.0, min(1.0, 1.0 - distance))


def keyword_match_density(text: str, terms: Sequence[str]) -> float:
    """How strongly a chunk's text carries the query terms, in ``[0, 1]``."""

    if not text or not terms:
        return 0.0
    lowered = text.lower()
    matched = 0
    covered = 0
    for term in terms:
        needle = term.lower()
        if not needle:
            continue
        occurrences = lowered.count(needle)
        if occurrences:
            matched += 1
        covered += occurrences * len(needle)
    if not matched:
        return 0.0
    coverage = matched / len(terms)
    density = min(1.0, covered / len(lowered))
    return KEYWORD_COVERAGE_WEIGHT * coverage + KEYWORD_DENSITY_WEIGHT * density


def recency_score(published_at: datetime | None, *, now: datetime) -> float:
    """Exponential decay on publish age, in ``[0, 1]``."""

    if published_at is None:
        return RECENCY_UNKNOWN_SCORE
    if published_at.tzinfo is None:
        # 库里理论上都是 timestamptz，但导入路径塞过 naive 值，别在这里炸。
        published_at = published_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - published_at).total_seconds() / 86_400.0)
    return float(0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS))


def source_quality_score(*, chunk_kind: str, source_kind: str | None, status: str | None) -> float:
    """A cheap trust prior for the hit, in ``[0, 1]``."""

    score = SOURCE_QUALITY_BASE
    if source_kind == "live":
        score += SOURCE_QUALITY_LIVE_BONUS
    if status == "published":
        score += SOURCE_QUALITY_PUBLISHED_BONUS
    if chunk_kind in SPOKEN_CHUNK_KINDS:
        score += SOURCE_QUALITY_SPOKEN_BONUS
    return min(1.0, score)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply_filters(statement: Any, *, workspace_id: UUID, filters: dict[str, Any]) -> Any:
    statement = statement.where(ContentEmbedding.workspace_id == workspace_id)
    chunk_kinds = filters.get("chunk_kinds")
    if chunk_kinds:
        statement = statement.where(ContentEmbedding.chunk_kind.in_(list(chunk_kinds)))
    platform_ids = filters.get("platform_ids")
    if platform_ids:
        statement = statement.where(ContentItem.platform_id.in_(list(platform_ids)))
    account_ids = filters.get("account_ids")
    if account_ids:
        statement = statement.where(ContentItem.account_id.in_(list(account_ids)))
    published_after = filters.get("published_after")
    if published_after is not None:
        statement = statement.where(ContentItem.published_at >= published_after)
    published_before = filters.get("published_before")
    if published_before is not None:
        statement = statement.where(ContentItem.published_at <= published_before)
    return statement


def build_breakdown(hit: ChunkHit, *, terms: Sequence[str]) -> ScoreBreakdown:
    """Assemble the debug trace for one chunk, including a readable sentence."""

    vector = vector_similarity(hit.distance)
    keyword = keyword_match_density(hit.text, terms)
    parts = [
        f"命中路径 {'+'.join(hit.matched_by) or '无'}",
        "向量相似度 " + ("不适用" if vector is None else f"{vector:.3f}"),
        f"关键词密度 {keyword:.3f}",
        f"RRF 融合分 {hit.rrf_score:.5f}",
    ]
    if hit.rerank is None:
        parts.append("未启用重排，最终排序按 RRF 名次")
    else:
        parts.append(
            f"重排分 {hit.rerank.score:.3f}"
            f"（新鲜度 {hit.rerank.recency:.3f}、来源质量 {hit.rerank.source:.3f}）"
        )
    return ScoreBreakdown(
        vector_score=vector,
        keyword_score=keyword,
        rrf_score=hit.rrf_score,
        rerank_score=None if hit.rerank is None else hit.rerank.score,
        explanation="；".join(parts) + "。",
    )


def attach_breakdowns(items: Sequence[ItemHit], *, terms: Sequence[str]) -> None:
    for item in items:
        for chunk in item.chunks:
            chunk.breakdown = build_breakdown(chunk, terms=terms)


class SemanticSearchService:
    """Vector + keyword retrieval over ``content_embeddings``."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        embedder: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._embedder = embedder or build_embedding_service(self._settings)

    @property
    def enabled(self) -> bool:
        return bool(self._settings.semantic_search_enabled)

    @property
    def rerank_enabled(self) -> bool:
        return bool(self._settings.rerank_enabled)

    @property
    def embedder(self) -> EmbeddingService:
        return self._embedder

    async def status(self, workspace_id: UUID) -> dict[str, Any]:
        model = self._embedder.model
        totals = (
            await self._session.execute(
                select(
                    func.count(ContentEmbedding.id),
                    func.count(func.distinct(ContentEmbedding.content_item_id)),
                ).where(
                    ContentEmbedding.workspace_id == workspace_id,
                    ContentEmbedding.model == model,
                )
            )
        ).one()
        by_kind = (
            await self._session.execute(
                select(ContentEmbedding.chunk_kind, func.count(ContentEmbedding.id))
                .where(
                    ContentEmbedding.workspace_id == workspace_id,
                    ContentEmbedding.model == model,
                )
                .group_by(ContentEmbedding.chunk_kind)
            )
        ).all()

        from app.tasks.embedding import build_pending_query

        pending_query = build_pending_query(
            model=model, workspace_id=workspace_id, reindex=False
        ).order_by(None)
        pending = int(
            await self._session.scalar(
                select(func.count()).select_from(pending_query.subquery())
            )
            or 0
        )

        return {
            "enabled": self.enabled and self._embedder.enabled,
            "backend": self._embedder.backend,
            "model": model,
            "dimension": self._embedder.dimension,
            "embedded_chunks": int(totals[0] or 0),
            "embedded_items": int(totals[1] or 0),
            "pending_items": pending,
            "chunk_kinds": {kind: int(count) for kind, count in by_kind},
        }

    async def search(
        self,
        workspace_id: UUID,
        *,
        query: str,
        mode: str = "hybrid",
        limit: int = 20,
        candidates: int = 120,
        chunk_kinds: Sequence[str] | None = None,
        platform_ids: Sequence[UUID] | None = None,
        account_ids: Sequence[UUID] | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise SemanticSearchDisabledError(
                "本地语义检索未启用，请设置 SIO_SEMANTIC_SEARCH_ENABLED=true"
            )

        started = time.perf_counter()
        filters: dict[str, Any] = {
            "chunk_kinds": list(chunk_kinds) if chunk_kinds else None,
            "platform_ids": list(platform_ids) if platform_ids else None,
            "account_ids": list(account_ids) if account_ids else None,
            "published_after": published_after,
            "published_before": published_before,
        }

        want_vector = mode in {"hybrid", "vector"}
        degraded = False
        vector_hits: list[ChunkHit] = []
        if want_vector:
            if self._embedder.enabled:
                try:
                    vector_hits = await self._vector_recall(
                        workspace_id, query=query, candidates=candidates, filters=filters
                    )
                except EmbeddingError:
                    # 后端挂了不该让搜索整个失败——降级成关键词，并如实告知前端。
                    degraded = True
            else:
                degraded = True

        keyword_hits: list[ChunkHit] = []
        if mode in {"hybrid", "keyword"} or degraded:
            keyword_hits = await self._keyword_recall(
                workspace_id, query=query, candidates=candidates, filters=filters
            )

        if mode == "vector" and degraded:
            mode_used = "keyword"
        elif mode == "vector":
            mode_used = "vector"
        elif mode == "keyword":
            mode_used = "keyword"
        else:
            mode_used = "keyword" if degraded else "hybrid"

        terms = tokenise_query(query)
        fused = self._fuse(vector_hits, keyword_hits)
        if self.rerank_enabled and fused:
            fused = await self._rerank(workspace_id, fused, terms=terms)

        items = await self._group_by_item(workspace_id, fused, limit=limit)
        if debug:
            # 只解释真正回传的块，避免为几百个候选白算一遍。
            attach_breakdowns(items, terms=terms)

        return {
            "query": query,
            "mode_requested": mode,
            "mode_used": mode_used,
            "degraded": degraded,
            "model": self._embedder.model if not degraded and want_vector else None,
            "total": len(items),
            "items": items,
            "took_ms": int((time.perf_counter() - started) * 1000),
        }

    async def _vector_recall(
        self,
        workspace_id: UUID,
        *,
        query: str,
        candidates: int,
        filters: dict[str, Any],
    ) -> list[ChunkHit]:
        vector = await self._embedder.embed_query(query)
        # 用 text 参数 + CAST 而不是直接绑定 vector 类型：asyncpg 只认识我们在
        # db/session.py 注册的 text codec，显式 CAST 最稳。
        query_vector = cast(
            bindparam("query_vector", value=encode_vector(vector), type_=String),
            Vector(self._embedder.dimension),
        )
        distance = ContentEmbedding.embedding.op("<=>", return_type=Float)(query_vector)

        statement = (
            select(
                ContentEmbedding.id,
                ContentEmbedding.content_item_id,
                ContentEmbedding.chunk_kind,
                ContentEmbedding.chunk_index,
                ContentEmbedding.text,
                ContentEmbedding.start_ms,
                ContentEmbedding.end_ms,
                ContentEmbedding.source_ref,
                distance.label("distance"),
            )
            .join(ContentItem, ContentItem.id == ContentEmbedding.content_item_id)
            .where(ContentEmbedding.model == self._embedder.model)
            .order_by(distance)
            .limit(candidates)
        )
        statement = _apply_filters(statement, workspace_id=workspace_id, filters=filters)

        rows = (await self._session.execute(statement)).all()
        return [
            ChunkHit(
                embedding_id=row[0],
                content_item_id=row[1],
                chunk_kind=row[2],
                chunk_index=row[3],
                text=row[4],
                start_ms=row[5],
                end_ms=row[6],
                source_ref=row[7],
                distance=float(row[8]) if row[8] is not None else None,
            )
            for row in rows
        ]

    async def _keyword_recall(
        self,
        workspace_id: UUID,
        *,
        query: str,
        candidates: int,
        filters: dict[str, Any],
    ) -> list[ChunkHit]:
        terms = tokenise_query(query)
        if not terms:
            return []

        lowered = func.lower(ContentEmbedding.text)
        conditions = []
        occurrence_terms = []
        for term in terms:
            pattern = f"%{_escape_like(term.lower())}%"
            conditions.append(lowered.like(pattern, escape="\\"))
            # 出现次数 = (原长 - 抠掉该词后的长度) / 词长
            occurrence_terms.append(
                (
                    func.char_length(lowered)
                    - func.char_length(func.replace(lowered, term.lower(), ""))
                )
                / float(len(term))
            )

        relevance = occurrence_terms[0]
        for extra in occurrence_terms[1:]:
            relevance = relevance + extra

        statement = (
            select(
                ContentEmbedding.id,
                ContentEmbedding.content_item_id,
                ContentEmbedding.chunk_kind,
                ContentEmbedding.chunk_index,
                ContentEmbedding.text,
                ContentEmbedding.start_ms,
                ContentEmbedding.end_ms,
                ContentEmbedding.source_ref,
                relevance.label("relevance"),
            )
            .join(ContentItem, ContentItem.id == ContentEmbedding.content_item_id)
            .where(ContentEmbedding.model == self._embedder.model)
            # 多词时先要求全部命中；一个都不满足的行直接不参与排序。
            .where(*conditions)
            .order_by(relevance.desc(), ContentEmbedding.chunk_index)
            .limit(candidates)
        )
        statement = _apply_filters(statement, workspace_id=workspace_id, filters=filters)

        rows = (await self._session.execute(statement)).all()
        hits = [
            ChunkHit(
                embedding_id=row[0],
                content_item_id=row[1],
                chunk_kind=row[2],
                chunk_index=row[3],
                text=row[4],
                start_ms=row[5],
                end_ms=row[6],
                source_ref=row[7],
            )
            for row in rows
        ]
        if hits or len(terms) == 1:
            return hits

        # 全词 AND 无结果时退回 OR，避免用户多打一个词就搜不到任何东西。
        statement = (
            select(
                ContentEmbedding.id,
                ContentEmbedding.content_item_id,
                ContentEmbedding.chunk_kind,
                ContentEmbedding.chunk_index,
                ContentEmbedding.text,
                ContentEmbedding.start_ms,
                ContentEmbedding.end_ms,
                ContentEmbedding.source_ref,
                relevance.label("relevance"),
            )
            .join(ContentItem, ContentItem.id == ContentEmbedding.content_item_id)
            .where(ContentEmbedding.model == self._embedder.model)
            .where(or_(*conditions))
            .order_by(relevance.desc(), ContentEmbedding.chunk_index)
            .limit(candidates)
        )
        statement = _apply_filters(statement, workspace_id=workspace_id, filters=filters)
        rows = (await self._session.execute(statement)).all()
        return [
            ChunkHit(
                embedding_id=row[0],
                content_item_id=row[1],
                chunk_kind=row[2],
                chunk_index=row[3],
                text=row[4],
                start_ms=row[5],
                end_ms=row[6],
                source_ref=row[7],
            )
            for row in rows
        ]

    def _fuse(
        self, vector_hits: Sequence[ChunkHit], keyword_hits: Sequence[ChunkHit]
    ) -> list[ChunkHit]:
        merged: dict[UUID, ChunkHit] = {}

        for rank, hit in enumerate(vector_hits, start=1):
            hit.score = VECTOR_WEIGHT / (RRF_K + rank)
            hit.matched_by = ["vector"]
            merged[hit.embedding_id] = hit

        for rank, hit in enumerate(keyword_hits, start=1):
            contribution = KEYWORD_WEIGHT / (RRF_K + rank)
            existing = merged.get(hit.embedding_id)
            if existing is None:
                hit.score = contribution
                hit.matched_by = ["keyword"]
                merged[hit.embedding_id] = hit
                continue
            existing.score += contribution
            if "keyword" not in existing.matched_by:
                existing.matched_by.append("keyword")

        for hit in merged.values():
            hit.rrf_score = hit.score

        return sorted(merged.values(), key=lambda hit: hit.score, reverse=True)

    async def _rerank(
        self, workspace_id: UUID, hits: list[ChunkHit], *, terms: Sequence[str]
    ) -> list[ChunkHit]:
        """Re-score the head of the fused list with cross features.

        只处理前 ``rerank_top_n`` 条：RRF 已经把明显不相关的压到后面，重排的价值
        集中在头部的次序调整上，全量重排只会白花一次内容表查询。
        """

        top_n = self._settings.rerank_top_n
        head = hits[:top_n]
        tail = hits[top_n:]

        signals = await self._item_signals(
            workspace_id, {hit.content_item_id for hit in head}
        )
        now = datetime.now(UTC)

        for hit in head:
            published_at, source_kind, status = signals.get(
                hit.content_item_id, (None, None, None)
            )
            vector = vector_similarity(hit.distance) or 0.0
            keyword = keyword_match_density(hit.text, terms)
            recency = recency_score(published_at, now=now)
            source = source_quality_score(
                chunk_kind=hit.chunk_kind, source_kind=source_kind, status=status
            )
            score = (
                RERANK_VECTOR_WEIGHT * vector
                + RERANK_KEYWORD_WEIGHT * keyword
                + RERANK_RECENCY_WEIGHT * recency
                + RERANK_SOURCE_WEIGHT * source
            )
            hit.rerank = RerankFeatures(
                vector=vector, keyword=keyword, recency=recency, source=source, score=score
            )
            hit.score = score

        # 名次分（≈0.03 量级）和重排分（0~1）不可比，尾部必须整体压到头部之下，
        # 否则一条没进重排的候选会凭量纲差异插队。相对次序保持不变。
        floor = min((hit.score for hit in head), default=0.0)
        for offset, hit in enumerate(tail, start=1):
            hit.score = floor / (1 + offset)

        head.sort(key=lambda hit: (hit.score, hit.rrf_score), reverse=True)
        return head + tail

    async def _item_signals(
        self, workspace_id: UUID, item_ids: Iterable[UUID]
    ) -> dict[UUID, tuple[datetime | None, str | None, str | None]]:
        ids = list(item_ids)
        if not ids:
            return {}
        rows = await self._session.execute(
            select(
                ContentItem.id,
                ContentItem.published_at,
                ContentItem.source_kind,
                ContentItem.status,
            ).where(
                ContentItem.id.in_(ids),
                ContentItem.workspace_id == workspace_id,
            )
        )
        return {row[0]: (row[1], row[2], row[3]) for row in rows.all()}

    async def _group_by_item(
        self, workspace_id: UUID, hits: Sequence[ChunkHit], *, limit: int
    ) -> list[ItemHit]:
        if not hits:
            return []

        grouped: dict[UUID, list[ChunkHit]] = {}
        for hit in hits:
            grouped.setdefault(hit.content_item_id, []).append(hit)

        # 内容分数 = 其最佳块的分数。用 max 而不是 sum，避免"块多的长视频"
        # 仅凭数量优势压过真正更相关的短视频。
        ranked = sorted(
            grouped.items(),
            key=lambda entry: max(hit.score for hit in entry[1]),
            reverse=True,
        )[:limit]
        item_ids = [item_id for item_id, _ in ranked]

        rows = await self._session.scalars(
            select(ContentItem).where(
                ContentItem.id.in_(item_ids),
                ContentItem.workspace_id == workspace_id,
            )
        )
        items = {item.id: item for item in rows.all()}

        results: list[ItemHit] = []
        for item_id in item_ids:
            item = items.get(item_id)
            if item is None:
                continue
            chunks = sorted(grouped[item_id], key=lambda hit: hit.score, reverse=True)
            results.append(
                ItemHit(
                    item=item,
                    score=chunks[0].score,
                    chunks=chunks[:MAX_CHUNKS_PER_HIT],
                )
            )
        return results
