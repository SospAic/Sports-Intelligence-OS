"""Tests for the 热点情报中心 module's core logic (no network / no LLM)."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.trends import TrendTopic
from app.services import derivative_engine as derivative_module
from app.services import search_analysis as search_module
from app.services.derivative_engine import (
    DerivativeService,
    _classify_angle,
    _normalise_search_result,
)
from app.services.platform_search import yt_search
from app.services.query_language import filter_english_results
from app.services.search_analysis import _detect_language, _heat_from_views, _result_heat


def _fake_topic(platform: str = "youtube", title: str = "巴黎奥运乒乓") -> TrendTopic:
    return TrendTopic(
        id=uuid4(),
        workspace_id=uuid4(),
        platform=platform,
        title=title,
        category="sport",
        heat_score=80.0,
        rank=1,
        sample_size=10,
        observed_at=__import__("datetime").datetime(2026, 8, 1),
    )


class _FakeSession:
    def __init__(self, topic: TrendTopic | None = None) -> None:
        self.topic = topic
        self.added: list[object] = []

    async def get(self, _model: object, _object_id: object) -> TrendTopic | None:
        return self.topic

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


    async def refresh(self, _value: object) -> None:
        return None


@pytest.mark.asyncio
async def test_yt_search_unsupported_platform_returns_note_without_network():
    results, note = await yt_search("tiktok", "anything", limit=5)
    assert results == []
    assert note is not None
    assert "未接入" in note


@pytest.mark.asyncio
async def test_english_platform_search_rejects_non_english_query_without_network():
    results, note = await yt_search(
        "youtube", "欧冠决赛", limit=5, query_language="en", region="US"
    )
    assert results == []
    assert note is not None
    assert "英文平台搜索" in note


@pytest.mark.asyncio
async def test_search_analysis_translates_query_before_platform_search(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def fake_search(*args: object, **kwargs: object):
        calls.append((args, kwargs))
        return ([{"title": "Champions League final analysis", "view_count": 100}], None)

    session = _FakeSession()
    service = search_module.SearchAnalysisService(session, None)  # type: ignore[arg-type]
    service._translate_texts = AsyncMock(return_value=["Champions League final"])  # type: ignore[method-assign]
    service._call_analysis_llm = AsyncMock(  # type: ignore[method-assign]
        return_value={"related_hotness": 20, "summary": "English summary"}
    )
    monkeypatch.setattr(search_module, "yt_search", fake_search)

    query, _analysis, results, _notice = await service.analyze(
        uuid4(), uuid4(), "欧冠决赛", platform="youtube", limit=5
    )

    assert query.query_text_en == "Champions League final"
    assert results[0]["title"] == "Champions League final analysis"
    assert calls == [
        (
            ("youtube", "Champions League final"),
            {"limit": 5, "query_language": "en", "region": "US"},
        )
    ]


@pytest.mark.asyncio
async def test_derivative_generation_translates_topic_before_platform_search(
    monkeypatch: pytest.MonkeyPatch,
):
    topic = _fake_topic(title="欧冠决赛")
    session = _FakeSession(topic)
    service = DerivativeService(session, None)  # type: ignore[arg-type]
    service._translate_texts = AsyncMock(return_value=["Champions League final"])  # type: ignore[method-assign]
    service._predict = AsyncMock(return_value=[])  # type: ignore[method-assign]
    service._populate_english_fields = AsyncMock()  # type: ignore[method-assign]
    service._run_items = AsyncMock(return_value=[])  # type: ignore[method-assign]
    search = AsyncMock(
        return_value=([{"title": "Champions League final recap", "view_count": 100}], None)
    )
    monkeypatch.setattr(derivative_module, "yt_search", search)

    await service.generate_for_topic(topic.workspace_id, topic.id, uuid4())  # type: ignore[arg-type]

    search.assert_awaited_once_with(
        "youtube",
        "Champions League final",
        limit=20,
        query_language="en",
        region="US",
    )


def test_english_result_filter_does_not_translate_non_english_sources():
    results = filter_english_results(
        [
            {"title": "Champions League final analysis"},
            {"title": "欧冠决赛分析"},
            {"title": ""},
        ]
    )
    assert [item["title"] for item in results] == [
        "Champions League final analysis",
        "",
    ]


def test_classify_angle_buckets_by_keywords():
    assert _classify_angle("乒乓球决赛深度解析") == "深度解析"
    assert _classify_angle("10分钟学会发球教程") == "教程教学"
    assert _classify_angle("年度名场面混剪") == "二创混剪"
    assert _classify_angle("完全看不懂的标题 xyz") == "其他角度"


def test_cluster_existing_groups_results_and_computes_heat():
    svc = DerivativeService(session=None, llm_providers=None, settings=None)  # type: ignore[arg-type]
    topic = _fake_topic()
    results = [
        {"title": "巴黎奥运乒乓 深度解析A", "view_count": 1_000_000, "url": "u1"},
        {"title": "巴黎奥运乒乓 深度解析B", "view_count": 100_000, "url": "u2"},
        {"title": "乒乓 混剪高光", "view_count": 50_000, "url": "u3"},
    ]
    rows = svc._cluster_existing(topic, results)
    angles = {r.angle for r in rows}
    assert "深度解析" in angles
    assert "二创混剪" in angles
    # heat is a 0-100 log-scaled proxy
    for r in rows:
        assert 0.0 <= (r.predicted_heat_score or 0) <= 100.0
    # median views for the 深度解析 bucket = (100_000 + 1_000_000)/2 = 550_000
    deep = next(r for r in rows if r.angle == "深度解析")
    expected = round(min(100.0, 12.0 * math.log10(550_000 + 1)), 1)
    assert deep.predicted_heat_score == expected
    assert deep.evidence_json["sample_count"] == 2


def test_heat_from_views_log_scale():
    assert _heat_from_views(0) == 0.0
    assert 0.0 < _heat_from_views(1_000_000) <= 100.0
    assert _heat_from_views(10**12) <= 100.0


def test_search_result_keeps_platform_metrics_and_labels_derived_heat():
    result = _normalise_search_result(
        {
            "title": "Match analysis",
            "view_count": 1_000_000,
            "like_count": 12_000,
            "comment_count": 800,
        }
    )

    assert result["view_count"] == 1_000_000
    assert result["like_count"] == 12_000
    assert result["comment_count"] == 800
    assert result["heat_score"] == _heat_from_views(1_000_000)
    assert result["metric_source"] == "platform_fields_and_log_view_proxy"


def test_search_heat_combines_returned_engagement_without_claiming_native_score():
    result = {
        "view_count": 1_000_000,
        "like_count": 10_000,
        "comment_count": 1_000,
    }

    assert _result_heat(result) > _heat_from_views(1_000_000)
    assert _result_heat({"view_count": None, "like_count": None}) == 0.0


def test_search_language_detection_supports_primary_input_languages():
    assert _detect_language("Champions League final") == "en"
    assert _detect_language("欧冠决赛") == "zh"
    assert _detect_language("チャンピオンズリーグ") == "ja"
    assert _detect_language("챔피언스리그") == "ko"
