"""Tests for the 热点情报中心 module's core logic (no network / no LLM)."""

from __future__ import annotations

import math

import pytest

from app.models.trends import TrendTopic
from app.services.derivative_engine import (
    DerivativeService,
    _classify_angle,
    _normalise_search_result,
)
from app.services.platform_search import yt_search
from app.services.search_analysis import _detect_language, _heat_from_views, _result_heat


def _fake_topic(platform: str = "youtube", title: str = "巴黎奥运乒乓") -> TrendTopic:
    return TrendTopic(
        workspace_id=__import__("uuid").uuid4(),
        platform=platform,
        title=title,
        category="sport",
        heat_score=80.0,
        rank=1,
        sample_size=10,
        observed_at=__import__("datetime").datetime(2026, 8, 1),
    )


@pytest.mark.asyncio
async def test_yt_search_unsupported_platform_returns_note_without_network():
    results, note = await yt_search("tiktok", "anything", limit=5)
    assert results == []
    assert note is not None
    assert "未接入" in note


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
