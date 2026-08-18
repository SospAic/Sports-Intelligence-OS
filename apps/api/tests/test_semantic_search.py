"""Coverage for the local (non-LLM) hybrid retrieval endpoint."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_engine_and_session
from app.models.embedding import ContentEmbedding
from app.models.monitoring import ContentItem
from app.services.semantic_search import (
    KEYWORD_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    RECENCY_UNKNOWN_SCORE,
    RRF_K,
    VECTOR_WEIGHT,
    ChunkHit,
    RerankFeatures,
    SemanticSearchService,
    build_breakdown,
    keyword_match_density,
    recency_score,
    source_quality_score,
    tokenise_query,
    vector_similarity,
)
from app.services.text_chunking import sha256_text

from .conftest import PG_ASYNC_URL, PG_SYNC_URL, TEST_PLATFORM_ID, TEST_REDIS_URL
from .test_content_indexing import StubEmbedder, fake_embed
from .test_monitoring_api import authenticate, create_account

_MODEL = "stub-model"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_tokenise_query_splits_on_whitespace() -> None:
    assert tokenise_query("刘翔 跨栏") == ["刘翔", "跨栏"]
    # 中文不分词：没有空格就整串匹配，避免把"跳水"拆成"跳"和"水"。
    assert tokenise_query("世锦赛跳水决赛") == ["世锦赛跳水决赛"]
    assert tokenise_query("   ") == []


def test_tokenise_query_caps_term_count() -> None:
    query = " ".join(f"w{index}" for index in range(20))
    assert len(tokenise_query(query, limit=5)) == 5


def _chunk(text: str) -> ChunkHit:
    return ChunkHit(
        embedding_id=uuid4(),
        content_item_id=uuid4(),
        chunk_kind="meta",
        chunk_index=0,
        text=text,
        start_ms=None,
        end_ms=None,
        source_ref=None,
    )


def test_fuse_boosts_chunks_found_by_both_paths() -> None:
    service = SemanticSearchService.__new__(SemanticSearchService)
    shared = _chunk("both")
    vector_only = _chunk("vector")
    keyword_echo = ChunkHit(
        embedding_id=shared.embedding_id,
        content_item_id=shared.content_item_id,
        chunk_kind="meta",
        chunk_index=0,
        text="both",
        start_ms=None,
        end_ms=None,
        source_ref=None,
    )

    fused = service._fuse([shared, vector_only], [keyword_echo])

    assert fused[0].embedding_id == shared.embedding_id
    assert fused[0].matched_by == ["vector", "keyword"]
    assert fused[0].score > fused[1].score
    assert fused[1].matched_by == ["vector"]


def test_fuse_keeps_keyword_only_hits() -> None:
    service = SemanticSearchService.__new__(SemanticSearchService)
    keyword_only = _chunk("keyword")
    fused = service._fuse([], [keyword_only])
    assert len(fused) == 1
    assert fused[0].matched_by == ["keyword"]
    assert fused[0].score > 0


# ---------------------------------------------------------------------------
# HTTP layer (real database + pgvector)
# ---------------------------------------------------------------------------


def _seed_contents(workspace_id: UUID, account_id: UUID, rows: list[tuple[str, str]]) -> list[UUID]:
    now = datetime.now(UTC)
    ids: list[UUID] = []
    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        for offset, (title, description) in enumerate(rows):
            content_id = uuid4()
            ids.append(content_id)
            session.add(
                ContentItem(
                    id=content_id,
                    workspace_id=workspace_id,
                    platform_id=TEST_PLATFORM_ID,
                    account_id=account_id,
                    external_id=f"content-{content_id.hex[:8]}",
                    content_type="video",
                    title=title,
                    description=description,
                    published_at=now - timedelta(days=offset),
                    duration_seconds=90,
                    canonical_url=f"https://example.com/{content_id.hex}",
                    language="zh-CN",
                    status="published",
                    metadata_json={},
                    tags=[],
                    first_seen_at=now,
                    last_seen_at=now - timedelta(minutes=offset),
                    source_kind="imported",
                    source_provider="test_fixture",
                    fetched_at=now,
                )
            )
        session.commit()
    engine.dispose()
    return ids


def _seed_embeddings(
    workspace_id: UUID, entries: list[tuple[UUID, str, str, int, int | None]]
) -> None:
    """Insert vectors through an async engine (asyncpg has the vector codec)."""

    async def _run() -> None:
        settings = Settings(
            environment="test",
            database_url=PG_ASYNC_URL,
            redis_url=TEST_REDIS_URL,
            secret_key="test-only-secret-not-used-in-production",
        )
        engine, session_factory = create_engine_and_session(settings)
        try:
            async with session_factory() as session:
                for content_id, kind, text, index, start_ms in entries:
                    session.add(
                        ContentEmbedding(
                            workspace_id=workspace_id,
                            content_item_id=content_id,
                            model=_MODEL,
                            dimension=len(fake_embed("x")),
                            chunk_kind=kind,
                            chunk_index=index,
                            text=text,
                            text_hash=sha256_text(text),
                            start_ms=start_ms,
                            end_ms=None if start_ms is None else start_ms + 3000,
                            source_ref=None,
                            embedding=fake_embed(text),
                        )
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _enable(client: TestClient, monkeypatch: pytest.MonkeyPatch, *, backend: bool = True) -> None:
    client.app.state.settings.semantic_search_enabled = True  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "app.services.semantic_search.build_embedding_service",
        lambda settings=None: StubEmbedder(enabled=backend),
    )


def test_query_returns_501_when_disabled(client: TestClient) -> None:
    authenticate(client)
    response = client.post("/api/v1/semantic-search/query", json={"query": "跳水"})
    assert response.status_code == 501
    # 应用统一用 RFC7807 problem+json：code 在顶层（http_exception_handler 会把
    # HTTPException(detail={code, detail}) 重写成顶层 code + 字符串 detail）。
    assert response.json()["code"] == "semantic_search_disabled"


def test_hybrid_query_ranks_the_semantically_closest_item_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    diving_id, football_id = _seed_contents(
        workspace_id,
        account_id,
        [
            ("世锦赛跳水决赛回放", "最后一跳完成反超。"),
            ("欧冠足球集锦", "补时阶段头球破门。"),
        ],
    )
    _seed_embeddings(
        workspace_id,
        [
            (diving_id, "meta", "世锦赛跳水决赛回放 最后一跳完成反超。", 0, None),
            (diving_id, "subtitle", "他在最后一跳完成反超，全场沸腾。", 0, 12000),
            (football_id, "meta", "欧冠足球集锦 补时阶段头球破门。", 0, None),
        ],
    )
    _enable(client, monkeypatch)

    response = client.post(
        "/api/v1/semantic-search/query",
        json={"query": "跳水决赛最后一跳反超", "limit": 5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["mode_used"] == "hybrid"
    assert payload["degraded"] is False
    assert payload["model"] == _MODEL
    assert payload["total"] >= 1
    assert payload["items"][0]["content_item_id"] == str(diving_id)
    assert payload["items"][0]["title"] == "世锦赛跳水决赛回放"
    best = payload["items"][0]["best_chunk"]
    assert "vector" in best["matched_by"]
    assert best["score"] > 0
    assert payload["took_ms"] >= 0


def test_subtitle_hit_exposes_seekable_time_range(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    (content_id,) = _seed_contents(workspace_id, account_id, [("决赛全场", "含完整解说。")])
    _seed_embeddings(
        workspace_id,
        [(content_id, "subtitle", "裁判亮出满分，比分被彻底改写。", 0, 45000)],
    )
    _enable(client, monkeypatch)

    response = client.post(
        "/api/v1/semantic-search/query",
        json={"query": "裁判亮出满分", "chunk_kinds": ["subtitle"]},
    )
    assert response.status_code == 200, response.text
    best = response.json()["items"][0]["best_chunk"]
    assert best["chunk_kind"] == "subtitle"
    assert best["start_ms"] == 45000
    assert best["end_ms"] == 48000


def test_query_degrades_to_keyword_when_backend_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    (content_id,) = _seed_contents(workspace_id, account_id, [("跳水决赛", "反超夺冠。")])
    _seed_embeddings(workspace_id, [(content_id, "meta", "跳水决赛 反超夺冠。", 0, None)])
    _enable(client, monkeypatch, backend=False)

    response = client.post("/api/v1/semantic-search/query", json={"query": "跳水决赛"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["degraded"] is True
    assert payload["mode_used"] == "keyword"
    assert payload["model"] is None
    assert payload["items"][0]["content_item_id"] == str(content_id)
    assert payload["items"][0]["best_chunk"]["matched_by"] == ["keyword"]


def test_query_filters_by_account(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    (content_id,) = _seed_contents(workspace_id, account_id, [("跳水决赛", "反超夺冠。")])
    _seed_embeddings(workspace_id, [(content_id, "meta", "跳水决赛 反超夺冠。", 0, None)])
    _enable(client, monkeypatch)

    response = client.post(
        "/api/v1/semantic-search/query",
        json={"query": "跳水决赛", "account_ids": [str(uuid4())]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_status_reports_index_coverage(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    indexed_id, pending_id = _seed_contents(
        workspace_id,
        account_id,
        [("已索引作品", "有向量。"), ("未索引作品", "还没有向量。")],
    )
    _seed_embeddings(
        workspace_id,
        [
            (indexed_id, "meta", "已索引作品 有向量。", 0, None),
            (indexed_id, "subtitle", "解说词片段。", 0, 1000),
        ],
    )
    _enable(client, monkeypatch)

    response = client.get("/api/v1/semantic-search/status")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["model"] == _MODEL
    assert payload["embedded_chunks"] == 2
    assert payload["embedded_items"] == 1
    assert payload["chunk_kinds"] == {"meta": 1, "subtitle": 1}
    assert payload["pending_items"] == 1
    assert payload["freshness"] == "stale"
    assert payload["latest_embedded_at"] is not None
    assert "尚未建立" in payload["freshness_detail"]
    assert pending_id is not None


def test_reindex_requires_embedding_backend(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    _enable(client, monkeypatch, backend=False)
    response = client.post(
        "/api/v1/semantic-search/reindex",
        headers={"X-CSRF-Token": csrf},
        json={"limit": 10},
    )
    assert response.status_code == 501
    assert response.json()["code"] == "embedding_backend_disabled"


def test_reindex_dispatches_backfill_task(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    _enable(client, monkeypatch)

    dispatched: dict[str, object] = {}

    class _Task:
        id = "task-123"

    def _delay(workspace_id: str, limit: int, reindex: bool) -> _Task:
        dispatched.update({"workspace_id": workspace_id, "limit": limit, "reindex": reindex})
        return _Task()

    monkeypatch.setattr("app.tasks.embedding.backfill_content_embeddings.delay", _delay)

    response = client.post(
        "/api/v1/semantic-search/reindex",
        headers={"X-CSRF-Token": csrf},
        json={"limit": 25, "reindex": True},
    )
    assert response.status_code == 202, response.text
    assert response.json() == {"task_id": "task-123", "limit": 25, "reindex": True}
    assert dispatched["limit"] == 25
    assert dispatched["reindex"] is True


def test_reindex_requires_csrf(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate(client)
    _enable(client, monkeypatch)
    response = client.post("/api/v1/semantic-search/reindex", json={"limit": 10})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Rerank features (pure scoring, no database)
# ---------------------------------------------------------------------------


def test_vector_similarity_clamps_to_unit_range() -> None:
    assert vector_similarity(None) is None
    assert vector_similarity(0.0) == 1.0
    assert vector_similarity(0.4) == pytest.approx(0.6)
    # 反向（distance > 1）对排序没有意义，截到 0 而不是给负分。
    assert vector_similarity(1.7) == 0.0


def test_keyword_match_density_rewards_full_term_coverage() -> None:
    terms = ["刘翔", "跨栏"]
    both = keyword_match_density("刘翔在跨栏决赛夺冠", terms)
    single = keyword_match_density("刘翔接受了赛后采访", terms)
    assert both > single > 0.0
    assert 0.0 <= both <= 1.0
    assert keyword_match_density("与查询无关的文本", terms) == 0.0
    assert keyword_match_density("", terms) == 0.0
    assert keyword_match_density("刘翔", []) == 0.0


def test_recency_score_halves_every_half_life() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    fresh = recency_score(now, now=now)
    aged = recency_score(now - timedelta(days=RECENCY_HALF_LIFE_DAYS), now=now)
    assert fresh == pytest.approx(1.0)
    assert aged == pytest.approx(0.5)
    # 缺发布时间给中性分，不能当成"很旧"来惩罚。
    assert recency_score(None, now=now) == RECENCY_UNKNOWN_SCORE
    # naive datetime 不该炸，按 UTC 处理。
    assert recency_score(datetime(2026, 8, 9), now=now) == pytest.approx(1.0)  # noqa: DTZ001


def test_source_quality_prefers_live_published_spoken_hits() -> None:
    best = source_quality_score(chunk_kind="subtitle", source_kind="live", status="published")
    worst = source_quality_score(chunk_kind="meta", source_kind="imported", status="removed")
    assert best == pytest.approx(1.0)
    assert worst == pytest.approx(0.4)
    assert 0.0 <= worst < best <= 1.0


def _rerank_service(*, top_n: int = 30) -> SemanticSearchService:
    service = SemanticSearchService.__new__(SemanticSearchService)
    service._settings = Settings(rerank_enabled=True, rerank_top_n=top_n)
    return service


def _fixed_signals(
    signals: dict[UUID, tuple[datetime | None, str | None, str | None]],
) -> object:
    async def _load(
        self: SemanticSearchService, workspace_id: UUID, item_ids: object
    ) -> dict[UUID, tuple[datetime | None, str | None, str | None]]:
        return signals

    return _load


def test_rerank_promotes_the_fresher_spoken_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale metadata hit can win on RRF alone and still lose after reranking."""

    now = datetime.now(UTC)
    stale = _chunk("三年前的赛事回顾页面简介")
    stale.distance = 0.05
    fresh = _chunk("刘翔在跨栏决赛夺冠")
    fresh.chunk_kind = "subtitle"
    fresh.distance = 0.35

    service = _rerank_service()
    # RRF：stale 排第一。
    fused = service._fuse([stale, fresh], [])
    assert fused[0].embedding_id == stale.embedding_id

    monkeypatch.setattr(
        SemanticSearchService,
        "_item_signals",
        _fixed_signals(
            {
                stale.content_item_id: (now - timedelta(days=1095), "imported", "published"),
                fresh.content_item_id: (now, "live", "published"),
            }
        ),
    )
    reranked = asyncio.run(service._rerank(uuid4(), fused, terms=["刘翔", "跨栏"]))

    assert reranked[0].embedding_id == fresh.embedding_id
    assert reranked[0].rerank is not None
    assert reranked[0].rerank.score == pytest.approx(reranked[0].score)
    assert 0.0 <= reranked[0].score <= 1.0
    assert reranked[0].score > reranked[1].score
    # 原始融合分被保留下来，解释和回归排查都要用。
    assert reranked[1].rrf_score == pytest.approx(VECTOR_WEIGHT / (RRF_K + 1))


def test_rerank_leaves_the_tail_below_the_reranked_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = [_chunk(f"候选 {index}") for index in range(4)]
    service = _rerank_service(top_n=2)
    fused = service._fuse(hits, [])
    monkeypatch.setattr(SemanticSearchService, "_item_signals", _fixed_signals({}))

    reranked = asyncio.run(service._rerank(uuid4(), fused, terms=["候选"]))

    head, tail = reranked[:2], reranked[2:]
    assert all(hit.rerank is not None for hit in head)
    # 尾部没有进重排窗口，也不能凭 RRF 的量纲差异插到头部前面。
    assert all(hit.rerank is None for hit in tail)
    assert min(hit.score for hit in head) > max(hit.score for hit in tail)
    assert [hit.embedding_id for hit in tail] == [hit.embedding_id for hit in fused[2:]]


def test_rerank_disabled_keeps_the_fused_ranking(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    (content_id,) = _seed_contents(workspace_id, account_id, [("跳水决赛", "反超夺冠。")])
    _seed_embeddings(workspace_id, [(content_id, "meta", "跳水决赛 反超夺冠。", 0, None)])
    _enable(client, monkeypatch)
    assert client.app.state.settings.rerank_enabled is False  # type: ignore[attr-defined]

    response = client.post("/api/v1/semantic-search/query", json={"query": "跳水决赛"})
    assert response.status_code == 200, response.text
    best = response.json()["items"][0]["best_chunk"]
    # 未重排时分数仍是 RRF 量纲：两路都排第一时正好取到上限 (1.0+0.8)/61 ≈ 0.0295。
    assert best["score"] == pytest.approx((VECTOR_WEIGHT + KEYWORD_WEIGHT) / (RRF_K + 1))


def test_rerank_enabled_returns_reranked_scores_within_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    ids = _seed_contents(
        workspace_id,
        account_id,
        [("跳水决赛回放", "反超夺冠。"), ("跳水决赛集锦", "全场高光。")],
    )
    _seed_embeddings(
        workspace_id,
        [(content_id, "meta", "跳水决赛 反超夺冠。", 0, None) for content_id in ids],
    )
    _enable(client, monkeypatch)
    client.app.state.settings.rerank_enabled = True  # type: ignore[attr-defined]

    response = client.post("/api/v1/semantic-search/query", json={"query": "跳水决赛", "limit": 1})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["items"]) == 1
    # 重排分是 0~1 的加权和，量纲明显高于 RRF 名次分。
    assert payload["items"][0]["score"] > (VECTOR_WEIGHT + KEYWORD_WEIGHT) / (RRF_K + 1)
    assert payload["items"][0]["score"] <= 1.0


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------


def test_build_breakdown_marks_rerank_as_not_applied() -> None:
    hit = _chunk("跳水决赛 反超夺冠")
    hit.distance = 0.2
    hit.matched_by = ["vector"]
    hit.rrf_score = 0.0164

    breakdown = build_breakdown(hit, terms=["跳水决赛"])

    assert breakdown.vector_score == pytest.approx(0.8)
    assert breakdown.keyword_score > 0.0
    assert breakdown.rrf_score == pytest.approx(0.0164)
    assert breakdown.rerank_score is None
    assert "未启用重排" in breakdown.explanation


def test_build_breakdown_reports_rerank_contributions() -> None:
    hit = _chunk("跳水决赛 反超夺冠")
    hit.matched_by = ["keyword"]
    hit.rerank = RerankFeatures(vector=0.0, keyword=0.9, recency=0.5, source=0.8, score=0.42)

    breakdown = build_breakdown(hit, terms=["跳水决赛"])

    # 纯关键词命中没有距离，向量分留空而不是伪造成 0。
    assert breakdown.vector_score is None
    assert breakdown.rerank_score == pytest.approx(0.42)
    assert "重排分 0.420" in breakdown.explanation
    assert "新鲜度 0.500" in breakdown.explanation


def _query_with_debug(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, debug: bool | None
) -> dict[str, object]:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    (content_id,) = _seed_contents(workspace_id, account_id, [("跳水决赛", "反超夺冠。")])
    _seed_embeddings(workspace_id, [(content_id, "meta", "跳水决赛 反超夺冠。", 0, None)])
    _enable(client, monkeypatch)

    body: dict[str, object] = {"query": "跳水决赛"}
    if debug is not None:
        body["debug"] = debug
    response = client.post("/api/v1/semantic-search/query", json=body)
    assert response.status_code == 200, response.text
    payload: dict[str, object] = response.json()
    return payload


def test_query_omits_score_breakdown_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _query_with_debug(client, monkeypatch, debug=None)
    item = payload["items"][0]  # type: ignore[index]
    assert item["score_breakdown"] is None
    assert item["best_chunk"]["score_breakdown"] is None


def test_query_returns_score_breakdown_when_debug_requested(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _query_with_debug(client, monkeypatch, debug=True)
    item = payload["items"][0]  # type: ignore[index]
    breakdown = item["score_breakdown"]

    assert breakdown == item["best_chunk"]["score_breakdown"]
    assert set(breakdown) == {
        "vector_score",
        "keyword_score",
        "rrf_score",
        "rerank_score",
        "explanation",
    }
    assert breakdown["vector_score"] is not None
    assert breakdown["keyword_score"] > 0.0
    assert breakdown["rrf_score"] > 0.0
    # 默认没开重排，这一项必须显式为 null。
    assert breakdown["rerank_score"] is None
    assert breakdown["explanation"]
    assert all(chunk["score_breakdown"] for chunk in item["chunks"])


def test_debug_and_rerank_combine_into_one_breakdown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    csrf = authenticate(client)
    account = create_account(client, csrf)
    workspace_id = UUID(account["workspace_id"])
    account_id = UUID(account["id"])

    (content_id,) = _seed_contents(workspace_id, account_id, [("跳水决赛", "反超夺冠。")])
    _seed_embeddings(workspace_id, [(content_id, "subtitle", "跳水决赛 反超夺冠。", 0, 1000)])
    _enable(client, monkeypatch)
    client.app.state.settings.rerank_enabled = True  # type: ignore[attr-defined]

    response = client.post(
        "/api/v1/semantic-search/query", json={"query": "跳水决赛", "debug": True}
    )
    assert response.status_code == 200, response.text
    breakdown = response.json()["items"][0]["score_breakdown"]
    assert breakdown["rerank_score"] is not None
    assert 0.0 <= breakdown["rerank_score"] <= 1.0
    assert "重排分" in breakdown["explanation"]
