"""Schemas for the on-demand download feature."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.download import Download


class DownloadCreate(BaseModel):
    url: str
    download_video: bool = True
    video_format: str = "best"
    write_subtitles: bool = True
    write_auto_subtitles: bool = False
    subtitle_langs: str = "zh.*,en.*"
    write_thumbnail: bool = True
    write_info_json: bool = False


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
