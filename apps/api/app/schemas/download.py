"""Schemas for the on-demand download feature."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DownloadCreate(BaseModel):
    url: str
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
    write_thumbnail: bool = True
    write_info_json: bool = False
    save_to_works: bool = False


class DownloadPreviewCreate(BaseModel):
    url: str


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
    media: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class DownloadPage(BaseModel):
    items: list[DownloadRead]
    page: int
    page_size: int
    total: int
