"""On-demand video / subtitle download records.

A ``Download`` is created when an operator submits a URL via the download page.
A Celery task fetches it with yt-dlp (reusing the same adapter CLI plumbing as
account sync) and stores the resulting media (video / subtitles / thumbnail /
info-json) under ``MEDIA_ROOT/downloads/<workspace>/<id>/``. The downloaded
files are served through ``GET /downloads/{id}/file/{file}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Download(Base, TimestampMixin):
    __tablename__ = "downloads"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Resolved yt-dlp download options (video format, subtitle langs, toggles).
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Mirror of ContentMedia: {base, video, thumbnail, info_json, subtitles[]}
    media: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
