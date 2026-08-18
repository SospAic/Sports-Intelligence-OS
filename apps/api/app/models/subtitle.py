"""Persistent jobs for local transcription and subtitle translation.

ASR and translation are deliberately tracked separately from platform sync and
on-demand downloads.  A model download or a long media transcription must not
hold an account lock or make a normal worker appear stuck.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SubtitleJob(TimestampMixin, Base):
    __tablename__ = "subtitle_jobs"
    __table_args__ = (
        Index("ix_subtitle_jobs_workspace_status", "workspace_id", "status"),
        Index("ix_subtitle_jobs_content_created", "content_item_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    asr_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    source_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
