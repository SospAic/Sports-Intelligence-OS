from __future__ import annotations

import asyncio
import json
import mimetypes
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import Settings


class VideoAnalyzerUnavailableError(RuntimeError):
    """The configured analyzer cannot read this source or is not configured."""


class VideoAnalyzerFailedError(RuntimeError):
    """The analyzer was callable but the external analysis failed."""


@dataclass(frozen=True)
class VideoAnalysisResult:
    matches_query: bool
    match_score: float
    summary: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    visual_tags: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    ocr_text: list[str] = field(default_factory=list)
    transcript_summary: str | None = None
    audio_events: list[str] = field(default_factory=list)
    match_basis: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    provider: str = "unknown"
    model: str | None = None
    source_kind: str = "live"


class VideoContentAnalyzer(Protocol):
    key: str
    model: str | None
    supported_platforms: frozenset[str]
    source_kind: str

    async def analyze(
        self,
        *,
        video_url: str,
        platform: str,
        query: str,
        metadata: dict[str, Any],
    ) -> VideoAnalysisResult: ...


def _extract_json(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise VideoAnalyzerFailedError("视频分析器返回了不可解析的 JSON") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise VideoAnalyzerFailedError("视频分析器返回了不可解析的 JSON") from exc
    if not isinstance(parsed, dict):
        raise VideoAnalyzerFailedError("视频分析器返回格式不是对象")
    return parsed


def _output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        for content in step.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks)
    raise VideoAnalyzerFailedError("视频分析器没有返回文本结果")


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_result(
    payload: dict[str, Any], *, provider: str, model: str | None, source_kind: str
) -> VideoAnalysisResult:
    score = payload.get("match_score", payload.get("score", 0))
    try:
        score = max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        score = 0.0
    segments = payload.get("segments")
    if not isinstance(segments, list):
        segments = []
    safe_segments = [item for item in segments if isinstance(item, dict)]
    matches = payload.get("matches_query", payload.get("match", False)) is True
    return VideoAnalysisResult(
        matches_query=matches,
        match_score=score,
        summary=str(payload.get("summary") or "").strip(),
        segments=safe_segments,
        visual_tags=_as_string_list(payload.get("visual_tags")),
        actions=_as_string_list(payload.get("actions")),
        objects=_as_string_list(payload.get("objects")),
        ocr_text=_as_string_list(payload.get("ocr_text")),
        transcript_summary=str(payload.get("transcript_summary") or "").strip() or None,
        audio_events=_as_string_list(payload.get("audio_events")),
        match_basis=_as_string_list(payload.get("match_basis")),
        raw=payload,
        provider=provider,
        model=model,
        source_kind=source_kind,
    )


def _is_public_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtube-nocookie.com",
    }


def _is_public_platform_url(value: str, platform: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {
        "youtube": {"youtube.com", "youtu.be", "youtube-nocookie.com"},
        "tiktok": {"tiktok.com"},
        "douyin": {"douyin.com"},
        "bilibili": {"bilibili.com", "b23.tv"},
    }.get(platform, set())
    return (
        parsed.scheme in {"http", "https"}
        and bool(host)
        and any(host == domain or host.endswith(f".{domain}") for domain in allowed)
    )


def build_analysis_prompt(query: str, metadata: dict[str, Any]) -> str:
    return "\n".join(
        [
            "你是严格的视频内容检索器。请只根据视频的画面、音频、语音转写、画面文字和动作判断是否符合查询。",
            "绝对不要根据标题、简介、标签、作者或 URL 命中；这些字段仅用于定位视频。",
            "",
            f"查询：{query}",
            f"候选元数据（禁止作为命中证据）：{json.dumps(metadata, ensure_ascii=False)}",
            "",
            "请只返回 JSON，不要 Markdown，字段必须包括：",
            "{",
            '  "matches_query": boolean,',
            '  "match_score": 0 到 1 的数字,',
            '  "summary": "视频内容摘要",',
            '  "segments": [{"start_seconds": 0, "end_seconds": 0, '
            '"evidence": "画面或声音中的具体证据"}],',
            '  "visual_tags": ["画面标签"],',
            '  "actions": ["动作"],',
            '  "objects": ["物体或人物"],',
            '  "ocr_text": ["画面文字"],',
            '  "transcript_summary": "语音内容摘要",',
            '  "audio_events": ["声音事件"],',
            '  "match_basis": ["visual", "audio", "transcript", "ocr", "action"]',
            "}",
            "只有存在可定位到时间段的内容证据时才可以 matches_query=true；无法确认时必须为 false。",
        ]
    )


class GeminiVideoAnalyzer:
    key = "gemini_video"
    supported_platforms = frozenset({"youtube", "tiktok", "douyin", "bilibili"})
    source_kind = "live"

    def __init__(self, settings: Settings) -> None:
        self._api_key = (
            settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        )
        self.model = settings.gemini_video_model
        self._timeout = settings.video_search_request_timeout_seconds
        self._max_upload_bytes = settings.video_search_max_upload_bytes

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def analyze(
        self,
        *,
        video_url: str,
        platform: str,
        query: str,
        metadata: dict[str, Any],
    ) -> VideoAnalysisResult:
        if not self._api_key:
            raise VideoAnalyzerUnavailableError("未配置 SIO_GEMINI_API_KEY")
        if platform not in self.supported_platforms or not _is_public_platform_url(
            video_url, platform
        ):
            raise VideoAnalyzerUnavailableError("Gemini URL 视频理解当前仅支持公开 YouTube 视频")
        if platform != "youtube":
            return await self._analyze_non_youtube(
                video_url=video_url, platform=platform, query=query, metadata=metadata
            )
        prompt = build_analysis_prompt(query, metadata)
        payload = {
            "model": self.model,
            "input": [
                {"type": "video", "uri": video_url},
                {"type": "text", "text": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/interactions",
                    headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise VideoAnalyzerFailedError(
                f"Gemini 视频分析失败（HTTP {exc.response.status_code}）：{detail}"
            ) from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            raise VideoAnalyzerFailedError(f"Gemini 视频分析请求失败：{exc}") from exc
        response_payload = response.json()
        return _parse_result(
            _extract_json(_output_text(response_payload)),
            provider=self.key,
            model=self.model,
            source_kind=self.source_kind,
        )

    async def _analyze_non_youtube(
        self,
        *,
        video_url: str,
        platform: str,
        query: str,
        metadata: dict[str, Any],
    ) -> VideoAnalysisResult:
        """Download an allowed public candidate and send it through Files API."""
        import shutil

        from app.adapters.platforms.yt_dlp import YtDlpAdapter

        temp_dir = Path(tempfile.mkdtemp(prefix="sio-video-search-"))
        uploaded_name: str | None = None
        try:
            entries, stderr = await YtDlpAdapter()._run_yt_dlp(
                video_url,
                download={
                    "download_video": True,
                    "video_quality": "720p",
                    "video_format": "mp4",
                    "naming_rule": "id",
                },
                media_dir=str(temp_dir),
                playlist_end=1,
            )
            media_files = await asyncio.to_thread(
                lambda: [
                    path
                    for path in temp_dir.rglob("*")
                    if path.is_file() and path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
                ]
            )
            if not entries or not media_files:
                raise VideoAnalyzerUnavailableError(
                    f"public video materialization returned no media: {stderr[:500]}"
                )
            media_path = await asyncio.to_thread(
                lambda: max(media_files, key=lambda path: path.stat().st_size)
            )
            media_size = await asyncio.to_thread(lambda: media_path.stat().st_size)
            if media_size > self._max_upload_bytes:
                raise VideoAnalyzerUnavailableError(
                    f"public video exceeds the analysis upload limit of "
                    f"{self._max_upload_bytes // 1_000_000} MB"
                )
            prompt = build_analysis_prompt(query, metadata)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                try:
                    uploaded_name, file_uri, mime_type = await self._upload_video(
                        client, media_path
                    )
                    response = await client.post(
                        "https://generativelanguage.googleapis.com/v1beta/interactions",
                        headers={
                            "x-goog-api-key": self._api_key or "",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "input": [
                                {
                                    "type": "video",
                                    "uri": file_uri,
                                    "mime_type": mime_type,
                                },
                                {"type": "text", "text": prompt},
                            ],
                        },
                    )
                    response.raise_for_status()
                    return _parse_result(
                        _extract_json(_output_text(response.json())),
                        provider=self.key,
                        model=self.model,
                        source_kind=self.source_kind,
                    )
                except httpx.HTTPStatusError as exc:
                    raise VideoAnalyzerFailedError(
                        f"Gemini video analysis failed (HTTP {exc.response.status_code})"
                    ) from exc
                except (httpx.HTTPError, TimeoutError) as exc:
                    raise VideoAnalyzerFailedError(f"Gemini video request failed: {exc}") from exc
                finally:
                    if uploaded_name:
                        try:
                            await client.delete(
                                f"https://generativelanguage.googleapis.com/v1beta/{uploaded_name}",
                                headers={"x-goog-api-key": self._api_key or ""},
                            )
                        except httpx.HTTPError:
                            pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _upload_video(
        self, client: httpx.AsyncClient, media_path: Path
    ) -> tuple[str, str, str]:
        size = await asyncio.to_thread(lambda: media_path.stat().st_size)
        mime_type = mimetypes.guess_type(media_path.name)[0] or "video/mp4"
        start = await client.post(
            "https://generativelanguage.googleapis.com/upload/v1beta/files",
            headers={
                "x-goog-api-key": self._api_key or "",
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": media_path.name}},
        )
        start.raise_for_status()
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise VideoAnalyzerFailedError("Gemini Files API did not return an upload URL")
        with media_path.open("rb") as handle:
            uploaded = await client.post(
                upload_url,
                headers={
                    "Content-Length": str(size),
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                },
                content=handle,
            )
        uploaded.raise_for_status()
        payload = uploaded.json().get("file") or {}
        name = str(payload.get("name") or "")
        uri = str(payload.get("uri") or "")
        if not name or not uri:
            raise VideoAnalyzerFailedError("Gemini Files API did not return a file URI")
        state = str(payload.get("state") or "")
        for _ in range(max(1, int(self._timeout // 5))):
            if state == "ACTIVE":
                return name, uri, mime_type
            if state == "FAILED":
                raise VideoAnalyzerFailedError("Gemini Files API failed to process the video")
            await asyncio.sleep(5)
            current = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/{name}",
                headers={"x-goog-api-key": self._api_key or ""},
            )
            current.raise_for_status()
            current_payload = current.json().get("file") or current.json()
            state = str(current_payload.get("state") or "")
            uri = str(current_payload.get("uri") or uri)
        raise VideoAnalyzerFailedError("Gemini Files API timed out while processing the video")


class MockVideoContentAnalyzer:
    key = "mock_video"
    model = "deterministic-test"
    supported_platforms = frozenset({"youtube", "tiktok", "douyin", "bilibili"})
    source_kind = "mock"

    async def analyze(
        self,
        *,
        video_url: str,
        platform: str,
        query: str,
        metadata: dict[str, Any],
    ) -> VideoAnalysisResult:
        return VideoAnalysisResult(
            matches_query=True,
            match_score=0.91,
            summary="测试分析器返回的确定性视频内容证据。",
            segments=[
                {"start_seconds": 0, "end_seconds": 5, "evidence": f"测试视频内容符合：{query}"}
            ],
            visual_tags=["test-video"],
            match_basis=["visual", "audio"],
            raw={"mock": True, "url": video_url, "platform": platform},
            provider=self.key,
            model=self.model,
            source_kind=self.source_kind,
        )


def build_video_content_analyzer(
    settings: Settings, *, requested_key: str | None = None
) -> VideoContentAnalyzer | None:
    if settings.video_search_analyzer == "gemini_video":
        if requested_key not in {None, "gemini_video"}:
            return None
        analyzer = GeminiVideoAnalyzer(settings)
        return analyzer if analyzer.configured else None
    if settings.video_search_analyzer == "mock" and settings.environment != "production":
        if requested_key not in {None, "mock", "mock_video"}:
            return None
        return MockVideoContentAnalyzer()
    return None
