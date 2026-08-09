import pytest

from app.core.config import Settings
from app.services.video_content_analyzer import (
    GeminiVideoAnalyzer,
    MockVideoContentAnalyzer,
    VideoAnalysisResult,
    VideoAnalyzerUnavailableError,
    build_analysis_prompt,
)
from app.services.video_content_search import strict_content_match


def test_metadata_only_result_is_not_a_video_content_match() -> None:
    result = VideoAnalysisResult(
        matches_query=True,
        match_score=0.99,
        summary="标题看起来相关",
        segments=[],
        match_basis=[],
    )

    assert strict_content_match(result, 0.65) is False


def test_content_match_requires_timestamped_evidence() -> None:
    result = VideoAnalysisResult(
        matches_query=True,
        match_score=0.8,
        summary="画面中出现冲刺",
        segments=[{"start_seconds": 12, "end_seconds": 18, "evidence": "运动员冲过终点"}],
        match_basis=["visual", "action"],
    )

    assert strict_content_match(result, 0.65) is True
    assert strict_content_match(result, 0.85) is False


def test_content_match_rejects_incomplete_or_invalid_timestamps() -> None:
    result = VideoAnalysisResult(
        matches_query=True,
        match_score=0.9,
        summary="valid-looking metadata",
        segments=[{"start_seconds": 12, "evidence": "missing end"}],
        match_basis=["visual"],
    )
    assert strict_content_match(result, 0.65) is False

    invalid = VideoAnalysisResult(
        matches_query=True,
        match_score=0.9,
        summary="reversed timestamps",
        segments=[{"start_seconds": 18, "end_seconds": 12, "evidence": "reversed"}],
        match_basis=["visual"],
    )
    assert strict_content_match(invalid, 0.65) is False


def test_prompt_explicitly_forbids_metadata_matching() -> None:
    prompt = build_analysis_prompt("视频里出现雨中冲刺", {"title": "雨中冲刺"})

    assert "不要根据标题、简介、标签、作者或 URL 命中" in prompt
    assert "segments" in prompt


@pytest.mark.asyncio
async def test_mock_analyzer_is_explicitly_marked_as_mock() -> None:
    analyzer = MockVideoContentAnalyzer()
    result = await analyzer.analyze(
        video_url="https://example.com/video",
        platform="bilibili",
        query="测试视频内容",
        metadata={},
    )

    assert result.source_kind == "mock"
    assert strict_content_match(result, 0.65) is True


@pytest.mark.asyncio
async def test_gemini_without_key_is_unavailable_not_success() -> None:
    analyzer = GeminiVideoAnalyzer(Settings(environment="test"))

    with pytest.raises(VideoAnalyzerUnavailableError):
        await analyzer.analyze(
            video_url="https://www.youtube.com/watch?v=test",
            platform="youtube",
            query="test",
            metadata={},
        )


def test_builder_does_not_advertise_unconfigured_gemini() -> None:
    from app.services.video_content_analyzer import build_video_content_analyzer

    settings = Settings(environment="test", video_search_analyzer="gemini_video")
    assert build_video_content_analyzer(settings) is None
