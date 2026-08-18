"""Read models for safe, read-only media storage inspection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StorageHealthRead(BaseModel):
    generated_at: datetime
    root_label: str = "media"
    quota_bytes: int | None = None
    quota_percent: float | None = None
    media_bytes: int = 0
    media_file_count: int = 0
    scan_truncated: bool = False
    orphan_file_count: int | None = None
    orphan_bytes: int | None = None
    volume_total_bytes: int | None = None
    volume_free_bytes: int | None = None
    tracked_artifact_count: int = 0
    tracked_ready_count: int = 0
    tracked_ready_bytes: int = 0
    artifact_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "automatic_cleanup": False,
            "destructive_actions_performed": False,
        }
    )


class StorageLifecycleCandidateRead(BaseModel):
    kind: str
    relative_path: str
    size_bytes: int | None = None
    reason: str
    action: str
    artifact_id: UUID | None = None
    artifact_kind: str | None = None
    retention_class: str | None = None
    eligible_at: datetime | None = None


class StorageLifecycleRead(BaseModel):
    generated_at: datetime
    workspace_id: UUID
    dry_run: bool
    automatic_cleanup_enabled: bool
    policy: dict[str, Any]
    scanned_file_count: int = 0
    scan_truncated: bool = False
    candidates: list[StorageLifecycleCandidateRead] = Field(default_factory=list)
    skipped: dict[str, int] = Field(default_factory=dict)
    deleted_file_count: int = 0
    deleted_bytes: int = 0
    marked_stale_count: int = 0
    failed: list[dict[str, str]] = Field(default_factory=list)
    audit_id: UUID | None = None


class StorageLifecycleExecuteRequest(BaseModel):
    confirm: bool = False
    dry_run: bool = True
    max_files: int | None = Field(default=None, ge=1, le=10_000)


class StorageRetentionUpdateRequest(BaseModel):
    retention_class: Literal["managed", "temporary", "protected"]
    retain_until: datetime | None = None
