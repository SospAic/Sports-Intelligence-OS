"""Lazy faster-whisper provider for the isolated subtitle worker."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.subtitle_timeline import TimedSegment, timeline_from_segments

logger = logging.getLogger(__name__)


class TranscriptionUnavailable(RuntimeError):
    """The configured ASR provider cannot be used in this deployment."""


class TranscriptionFailed(RuntimeError):
    """The provider was available but failed to process the media."""


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    segments: list[TimedSegment]
    provider: str = "faster_whisper"


@lru_cache(maxsize=2)
def _load_model(model_name: str, device: str, compute_type: str, model_dir: str) -> Any:
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised in deployment smoke tests
        raise TranscriptionUnavailable(
            "faster-whisper 未安装，请重建 subtitle-worker 镜像"
        ) from exc

    Path(model_dir).mkdir(parents=True, exist_ok=True)
    try:
        return WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=model_dir,
        )
    except Exception as exc:  # noqa: BLE001 - model/runtime errors are user-facing job errors
        raise TranscriptionUnavailable(f"无法加载 faster-whisper 模型：{str(exc)[:500]}") from exc


class FasterWhisperTranscriber:
    def __init__(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        model_dir: str,
        beam_size: int = 5,
        max_duration_seconds: int = 7200,
    ) -> None:
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.model_dir = model_dir
        self.beam_size = beam_size
        self.max_duration_seconds = max_duration_seconds

    def transcribe(
        self,
        media_path: str,
        *,
        language: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> TranscriptionResult:
        try:
            model = _load_model(self.model, self.device, self.compute_type, self.model_dir)
            if progress:
                progress("模型已加载，开始提取逐词时间轴")
            segments, info = model.transcribe(
                media_path,
                language=language or None,
                beam_size=self.beam_size,
                word_timestamps=True,
                vad_filter=True,
            )
            materialised = list(segments)
            duration = getattr(info, "duration", None)
            if duration is not None and float(duration) > self.max_duration_seconds:
                raise TranscriptionFailed(
                    f"媒体时长超过本地 ASR 安全上限 {self.max_duration_seconds} 秒"
                )
            timeline, _ = timeline_from_segments(materialised)
            if not timeline:
                raise TranscriptionFailed("ASR 未返回可读语音片段")
            return TranscriptionResult(
                language=str(getattr(info, "language", "") or language or "und"),
                language_probability=(
                    float(info.language_probability)
                    if getattr(info, "language_probability", None) is not None
                    else None
                ),
                duration_seconds=float(duration) if duration is not None else None,
                segments=timeline,
            )
        except (TranscriptionUnavailable, TranscriptionFailed):
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider failures for the job API
            logger.exception("faster_whisper_transcription_failed", extra={"path": media_path})
            raise TranscriptionFailed(f"faster-whisper 处理失败：{str(exc)[:500]}") from exc
