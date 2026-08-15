"""Dedicated ASR and translation worker tasks.

Only this module loads a speech model. Account monitoring, media downloads and
the normal Celery worker never import model weights or consume the ``subtitle``
queue, so a slow first model download cannot make sync look frozen.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.monitoring import ContentItem
from app.models.subtitle import SubtitleJob
from app.providers.transcription.faster_whisper import (
    FasterWhisperTranscriber,
    TranscriptionFailed,
    TranscriptionUnavailable,
)
from app.providers.translation.http import HttpTranslationProvider, TranslationUnavailable
from app.services.subtitle_timeline import (
    TimedSegment,
    clean_transcript_text,
    has_word_timestamps,
    render_cue_vtt,
    render_word_timed_vtt,
    timeline_json,
)
from app.services.subtitle_tools import MEDIA_ROOT, _recorded_path
from app.services.text_chunking import SubtitleCue, parse_subtitle
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class SubtitleProcessingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _safe_name(value: str, fallback: str = "subtitle") -> str:
    cleaned = _SAFE_NAME.sub("-", value.strip()).strip(".-_")
    return cleaned[:80] or fallback


def _append_log(progress: dict[str, Any], message: str, level: str = "info") -> dict[str, Any]:
    next_progress = dict(progress)
    logs = list(next_progress.get("log") or [])
    logs.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "level": level if level in {"info", "warn", "error"} else "info",
            "message": message[:500],
        }
    )
    next_progress["log"] = logs[-100:]
    next_progress["message"] = message[:500]
    next_progress["updated_at"] = datetime.now(UTC).isoformat()
    return next_progress


async def _set_progress(
    session: Any,
    job: SubtitleJob,
    *,
    stage: str,
    percent: int,
    message: str,
    level: str = "info",
    status: str | None = None,
) -> None:
    progress = dict(job.progress or {})
    progress["stage"] = stage
    progress["percent"] = max(0, min(100, int(percent)))
    job.progress = _append_log(progress, message, level)
    if status is not None:
        job.status = status
    await session.commit()


def _language_candidates(value: str) -> set[str]:
    cleaned = value.strip().casefold()
    if not cleaned:
        return set()
    candidates = {cleaned}
    if "-" in cleaned:
        candidates.add(cleaned.split("-", 1)[0])
    if "_" in cleaned:
        candidates.add(cleaned.split("_", 1)[0])
    if "." in cleaned:
        candidates.add(cleaned.split(".", 1)[0])
    return candidates


def _find_source_track(media: dict[str, Any], requested: str | None) -> dict[str, str] | None:
    tracks = [
        {
            "lang": str(item.get("lang") or item.get("language") or "").strip(),
            "file": str(item.get("file") or "").strip(),
        }
        for item in media.get("subtitles") or []
        if isinstance(item, dict) and item.get("file")
    ]
    tracks = [track for track in tracks if track["lang"] and track["file"]]
    if not tracks:
        return None
    if requested:
        requested_set = _language_candidates(requested)
        exact = [track for track in tracks if track["lang"].casefold() == requested.casefold()]
        matches = [
            track
            for track in tracks
            if _language_candidates(track["lang"]) & requested_set
        ]
        return (exact or matches or [tracks[0]])[0]
    return tracks[0]


def _read_media_text(base: str, filename: str) -> str:
    path = _recorded_path(base, filename, MEDIA_ROOT)
    if not path.is_file():
        raise SubtitleProcessingError("subtitle_file_missing", f"字幕文件不存在：{filename}")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise SubtitleProcessingError("subtitle_file_too_large", "原始字幕超过 8 MB 安全上限")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SubtitleProcessingError("subtitle_encoding_invalid", "原始字幕编码无法识别")


def _write_artifact(base: str, filename: str, content: str) -> None:
    path = _recorded_path(base, filename, MEDIA_ROOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _append_track(media: dict[str, Any], entry: dict[str, Any]) -> None:
    tracks = [item for item in media.get("subtitles") or [] if isinstance(item, dict)]
    tracks = [item for item in tracks if item.get("file") != entry.get("file")]
    # Generated tracks are placed first so the UI defaults to the word-timed
    # version while retaining every original platform file in the manifest.
    media["subtitles"] = [entry, *tracks]


def _append_artifact(media: dict[str, Any], entry: dict[str, Any]) -> None:
    artifacts = [item for item in media.get("subtitle_artifacts") or [] if isinstance(item, dict)]
    artifacts = [item for item in artifacts if item.get("file") != entry.get("file")]
    media["subtitle_artifacts"] = [*artifacts, entry]


def _base_language(value: str | None) -> str | None:
    cleaned = (value or "").strip().replace("_", "-")
    return cleaned.split("-", 1)[0] if cleaned else None


def _cues_from_segments(segments: list[TimedSegment]) -> list[SubtitleCue]:
    return [
        SubtitleCue(start_ms=segment.start_ms, end_ms=segment.end_ms, text=segment.text)
        for segment in segments
    ]


async def _translate(
    *,
    settings: Any,
    source_language: str | None,
    cues: list[SubtitleCue],
    target_language: str,
) -> list[SubtitleCue]:
    if (
        settings.subtitle_translation_backend != "http"
        or not settings.subtitle_translation_base_url
    ):
        raise TranslationUnavailable(
            "未配置本地翻译服务；请设置 SIO_SUBTITLE_TRANSLATION_BACKEND=http 和 BASE_URL"
        )
    if len(cues) > settings.subtitle_translation_max_segments:
        raise TranslationUnavailable(
            f"字幕分段数超过翻译安全上限 {settings.subtitle_translation_max_segments}"
        )
    provider = HttpTranslationProvider(
        base_url=settings.subtitle_translation_base_url,
        api_key=(
            settings.subtitle_translation_api_key.get_secret_value()
            if settings.subtitle_translation_api_key
            else None
        ),
        timeout_seconds=settings.subtitle_translation_timeout_seconds,
    )
    translated: list[str] = []
    # Keep batches bounded so one exceptionally long transcript cannot create a
    # giant request body or monopolise the local translation service.
    for start in range(0, len(cues), 64):
        translated.extend(
            await provider.translate_segments(
                    [cue.text for cue in cues[start : start + 64]],
                # Keep the full platform/product code here. The HTTP provider
                # maps und-auto -> auto and zh -> LibreTranslate's zh-Hans.
                source_language=source_language,
                target_language=target_language,
            )
        )
    return [
        SubtitleCue(start_ms=cue.start_ms, end_ms=cue.end_ms, text=clean_transcript_text(text))
        for cue, text in zip(cues, translated, strict=True)
    ]


async def _run(job_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            job = await session.scalar(select(SubtitleJob).where(SubtitleJob.id == job_id))
            if job is None:
                return {"status": "missing", "job_id": str(job_id)}
            content = await session.scalar(
                select(ContentItem).where(
                    ContentItem.id == job.content_item_id,
                    ContentItem.workspace_id == job.workspace_id,
                )
            )
            if content is None:
                job.status = "failed"
                job.error_code = "content_not_found"
                job.error_detail = "作品不存在或已被删除"
                await session.commit()
                return {"status": "failed", "error_code": job.error_code}

            job.status = "running"
            job.error_code = None
            job.error_detail = None
            await _set_progress(
                session,
                job,
                stage="prepare",
                percent=5,
                message="已进入独立字幕任务队列，检查原始字幕与媒体文件",
            )
            media = dict(content.media or {})
            base = str(media.get("base") or "").strip()
            if not base:
                raise SubtitleProcessingError("media_manifest_missing", "作品没有可用的媒体目录")

            requested_language = (job.source_language or content.language or "").strip() or None
            source_track = _find_source_track(media, requested_language)
            source_language = requested_language
            source_kind = "asr"
            source_file: str | None = None
            source_segments: list[TimedSegment] = []
            source_cues: list[SubtitleCue] = []
            word_timed = False

            if source_track:
                raw_source = _read_media_text(base, source_track["file"])
                parsed_cues = parse_subtitle(raw_source)
                if not parsed_cues:
                    raise SubtitleProcessingError(
                        "subtitle_empty", f"原始字幕轨道为空：{source_track['lang']}"
                    )
                source_language = source_track["lang"]
                source_file = source_track["file"]
                source_cues = parsed_cues
                word_timed = has_word_timestamps(raw_source)
                source_kind = "platform_subtitle"
                await _set_progress(
                    session,
                    job,
                    stage="source",
                    percent=25,
                    message=(
                        f"已复用平台原字幕：{source_track['lang']}；翻译将严格沿用原字幕时间轴"
                        + ("，并保留逐词标记" if word_timed else "")
                    ),
                )

            if not source_track:
                video_file = str(media.get("video") or "").strip()
                if not video_file:
                    raise SubtitleProcessingError(
                        "media_video_missing",
                        "没有可用于 ASR 的本地视频；请先下载视频或提供带逐词时间轴的原始字幕",
                    )
                video_path = _recorded_path(base, video_file, MEDIA_ROOT)
                if not video_path.is_file():
                    raise SubtitleProcessingError("media_video_missing", "本地视频文件不存在")
                if video_path.stat().st_size > settings.subtitle_asr_max_file_bytes:
                    raise SubtitleProcessingError(
                        "media_video_too_large", "视频超过 ASR 文件大小安全上限"
                    )
                if (
                    not settings.subtitle_asr_enabled
                    or settings.subtitle_asr_backend != "faster_whisper"
                ):
                    raise SubtitleProcessingError(
                        "asr_not_configured",
                        "未启用 faster-whisper；请配置 "
                        "SIO_SUBTITLE_ASR_ENABLED=true、BACKEND=faster_whisper",
                    )
                await _set_progress(
                    session,
                    job,
                    stage="asr",
                    percent=20,
                    message=(
                        "开始加载 faster-whisper；首次运行可能需要下载模型，"
                        "过程不会占用账号同步队列"
                    ),
                )
                transcriber = FasterWhisperTranscriber(
                    model=settings.subtitle_asr_model,
                    device=settings.subtitle_asr_device,
                    compute_type=settings.subtitle_asr_compute_type,
                    model_dir=settings.subtitle_asr_model_dir,
                    beam_size=settings.subtitle_asr_beam_size,
                    max_duration_seconds=settings.subtitle_asr_max_duration_seconds,
                )
                progress_messages: list[str] = []
                transcription = await asyncio.to_thread(
                    transcriber.transcribe,
                    str(video_path),
                    language=_base_language(source_language),
                    progress=progress_messages.append,
                )
                for message in progress_messages:
                    await _set_progress(
                        session,
                        job,
                        stage="asr",
                        percent=45,
                        message=message,
                    )
                source_language = transcription.language or source_language or "und"
                source_segments = transcription.segments
                source_cues = _cues_from_segments(source_segments)
                word_timed = any(segment.words for segment in source_segments)
                if not word_timed:
                    raise SubtitleProcessingError(
                        "asr_word_timestamps_missing",
                        "faster-whisper 未返回逐词时间轴，已停止生成不精确的卡拉 OK字幕",
                    )
                source_file = (
                    "asr-"
                    f"{_safe_name(source_language, 'und')}-"
                    f"{_safe_name(settings.subtitle_asr_model)}.vtt"
                )
                manifest_file = f"{Path(source_file).stem}.json"
                _write_artifact(base, source_file, render_word_timed_vtt(source_segments))
                _write_artifact(
                    base,
                    manifest_file,
                    timeline_json(source_segments, language=source_language),
                )
                _append_track(
                    media,
                    {
                        "lang": source_language,
                        "file": source_file,
                        "source": "asr",
                        "word_timed": True,
                        "model": settings.subtitle_asr_model,
                    },
                )
                _append_artifact(
                    media,
                    {
                        "lang": source_language,
                        "file": manifest_file,
                        "kind": "word_timeline_json",
                        "source": "asr",
                    },
                )
                await _set_progress(
                    session,
                    job,
                    stage="asr",
                    percent=60,
                    message=f"ASR 完成：{len(source_segments)} 条片段，已生成逐词时间轴与原文字幕",
                )

            generated_tracks: list[dict[str, Any]] = []
            translation_errors: list[str] = []
            for index, target_language in enumerate(job.target_languages or []):
                target = target_language.strip()
                if not target or _base_language(target) == _base_language(source_language):
                    continue
                try:
                    await _set_progress(
                        session,
                        job,
                        stage="translation",
                        percent=60 + int(index * 30 / max(1, len(job.target_languages))),
                        message=f"正在生成 {target} 翻译轨道（保留原文时间轴，不覆盖原始字幕）",
                    )
                    translated_cues = await _translate(
                        settings=settings,
                        source_language=source_language,
                        cues=source_cues,
                        target_language=target,
                    )
                    translated_file = (
                        "translation-"
                        f"{_safe_name(source_language or 'und')}-to-"
                        f"{_safe_name(target)}.vtt"
                    )
                    _write_artifact(base, translated_file, render_cue_vtt(translated_cues))
                    entry = {
                        "lang": target,
                        "file": translated_file,
                        "source": "local_translation",
                        "word_timed": False,
                        "source_language": source_language,
                    }
                    _append_track(media, entry)
                    generated_tracks.append(entry)
                except TranslationUnavailable as exc:
                    translation_errors.append(f"{target}: {exc}")
                    await _set_progress(
                        session,
                        job,
                        stage="translation",
                        percent=70,
                        message=f"{target} 翻译未完成：{str(exc)[:300]}",
                        level="warn",
                    )

            content.media = media
            result = {
                "source_file": source_file,
                "source_language": source_language,
                "source_kind": source_kind,
                "word_timed": word_timed,
                "generated_tracks": generated_tracks,
                "translation_errors": translation_errors,
            }
            job.result = result
            job.status = "degraded" if translation_errors else "succeeded"
            if translation_errors:
                job.error_code = "translation_degraded"
                job.error_detail = "；".join(translation_errors)[:2000]
            job.progress = _append_log(
                {**dict(job.progress or {}), "stage": "complete", "percent": 100},
                "字幕任务完成：原文轨道已保存；翻译轨道按实际可用性单独记录",
                "warn" if translation_errors else "info",
            )
            await session.commit()
            return {"status": job.status, "job_id": str(job.id), "result": result}
    except (SubtitleProcessingError, TranscriptionUnavailable, TranscriptionFailed) as exc:
        async with session_factory() as session:
            job = await session.scalar(select(SubtitleJob).where(SubtitleJob.id == job_id))
            if job is not None:
                job.status = "failed"
                job.error_code = getattr(exc, "code", "asr_failed")
                job.error_detail = str(exc)[:2000]
                job.progress = _append_log(
                    {**dict(job.progress or {}), "stage": "failed", "percent": 100},
                    str(exc),
                    "error",
                )
                await session.commit()
        return {"status": "failed", "job_id": str(job_id), "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - persist an auditable terminal failure
        logger.exception("subtitle_job_failed", extra={"job_id": str(job_id)})
        async with session_factory() as session:
            job = await session.scalar(select(SubtitleJob).where(SubtitleJob.id == job_id))
            if job is not None:
                job.status = "failed"
                job.error_code = "subtitle_job_failed"
                job.error_detail = str(exc)[:2000]
                job.progress = _append_log(
                    {**dict(job.progress or {}), "stage": "failed", "percent": 100},
                    "字幕任务异常终止：" + str(exc)[:400],
                    "error",
                )
                await session.commit()
        return {"status": "failed", "job_id": str(job_id), "error": str(exc)[:500]}
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.subtitles.generate_content_subtitles",
    bind=True,
    max_retries=0,
)
def generate_content_subtitles(self: Task, job_id: str) -> dict[str, Any]:
    del self
    return asyncio.run(_run(UUID(job_id)))
