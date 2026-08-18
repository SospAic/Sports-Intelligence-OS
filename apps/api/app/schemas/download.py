"""Schemas for the on-demand download feature."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.monitoring import MediaArtifactRead


class DownloadCreate(BaseModel):
    url: str
    # Optional owner content used by the content-detail download buttons. It
    # lets completed artifacts be merged back into that exact work instead of
    # relying on uploader/channel heuristics.
    content_id: UUID | None = None
    download_video: bool = True
    # 视频清晰度: best / 2160p / 1440p / 1080p / 720p / 480p / audio(仅音频)
    video_quality: str = "best"
    # 视频格式(容器): best / mp4 / webm / mkv
    video_format: str = "best"
    # 音频格式(仅 audio 清晰度时生效): best / mp3 / m4a / aac / opus / wav / flac
    audio_format: str = "best"
    # 码率(仅音频提取时生效): 空 / 320K / 256K / 192K / 128K
    bitrate: str = ""
    # 命名规则(输出文件名): id / title / uploader / date_title
    naming_rule: str = "id"
    write_subtitles: bool = True
    write_auto_subtitles: bool = False
    subtitle_langs: str = "zh.*,en.*"
    # The UI exposes these as two independent tracks. ``subtitle_langs`` is
    # kept for older clients and scheduled jobs that still send the wildcard
    # filter directly.
    subtitle_primary_lang: str = ""
    subtitle_secondary_lang: str = ""
    subtitle_show_timestamps: bool = False
    write_thumbnail: bool = True
    write_info_json: bool = False
    save_to_works: bool = False


class DownloadPreviewCreate(BaseModel):
    url: str


class DownloadSubtitleTrack(BaseModel):
    language: str
    kind: Literal["manual", "automatic"]


SubtitleExportFormat = Literal["vtt", "srt", "txt", "json", "ass"]


class SubtitleExportCreate(BaseModel):
    """Parameters for turning one or two archived tracks into a subtitle asset."""

    primary_lang: str = Field(min_length=1, max_length=64)
    secondary_lang: str = Field(default="", max_length=64)
    format: SubtitleExportFormat = "srt"
    show_timestamps: bool = False


class SubtitleCueRead(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class SubtitlePreviewRead(BaseModel):
    primary_lang: str
    secondary_lang: str = ""
    format: SubtitleExportFormat = "srt"
    show_timestamps: bool = False
    cue_count: int
    cues: list[SubtitleCueRead] = Field(default_factory=list)
    rendered_text: str
    source_files: list[str] = Field(default_factory=list)
    generated_file: str | None = None


class SubtitleGenerateCreate(BaseModel):
    """Request local transcription and optional independent translation tracks."""

    source_language: str | None = Field(default=None, max_length=32)
    target_languages: list[str] = Field(default_factory=lambda: ["zh"], max_length=8)
    force: bool = False


class SubtitleJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    content_item_id: UUID
    status: Literal["queued", "running", "succeeded", "degraded", "failed"]
    asr_backend: str
    source_language: str | None = None
    target_languages: list[str] = Field(default_factory=list)
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    updated_at: datetime


class DownloadPreviewRead(BaseModel):
    url: str
    platform: str | None = None
    external_id: str | None = None
    title: str | None = None
    uploader: str | None = None
    thumbnail: str | None = None
    duration_seconds: float | None = None
    description: str | None = None
    subtitle_languages: list[str] = Field(default_factory=list)
    subtitle_tracks: list[DownloadSubtitleTrack] = Field(default_factory=list)
    notice: str | None = None
    source_kind: str = "live"


class DownloadPreviewEnqueue(BaseModel):
    """Returned by ``POST /downloads/preview``; the real parse runs in Celery."""

    task_id: str


class DownloadPreviewPoll(BaseModel):
    """Returned by ``GET /downloads/preview/{task_id}`` while polling."""

    task_id: str
    state: Literal["PENDING", "STARTED", "SUCCESS", "FAILURE", "REVOKED"]
    preview: DownloadPreviewRead | None = None
    error_code: int | None = None
    error_detail: str | None = None


class YtDlpRuntimeRead(BaseModel):
    node_configured_path: str | None = None
    node_resolved_path: str | None = None
    node_available: bool = False
    node_version: str | None = None
    yt_dlp_version: str | None = None
    ejs_package_expected: bool = True
    remote_components: list[str] = Field(default_factory=list)
    update_enabled: bool = False
    update_command: str
    update_note: str
    status: Literal["ready", "degraded"]
    detail: str


class DownloadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    url: str
    platform: str | None = None
    status: str
    error: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    media: dict[str, Any] | None = None
    artifacts: list[MediaArtifactRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DownloadPage(BaseModel):
    items: list[DownloadRead]
    page: int
    page_size: int
    total: int
