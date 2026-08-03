"""Serve locally-archived media (thumbnail / video / subtitles / info-json).

Files are written by download-capable adapters under ``MEDIA_ROOT`` during a
sync and referenced from ``ContentItem.media``. This endpoint resolves a stored
*relative* path, enforces workspace ownership, and guards against path
traversal before streaming the bytes back to the detail page.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.dependencies import CurrentAuth, DatabaseSession
from app.models.monitoring import ContentItem

router = APIRouter(tags=["media"])

#: Default media root; overridable per deployment via the SIO_MEDIA_ROOT env var.
MEDIA_ROOT = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")

_EXT_CONTENT_TYPE: dict[str, str] = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".flv": "video/x-flv",
    ".m4v": "video/mp4",
    ".avi": "video/x-msvideo",
    ".vtt": "text/vtt",
    ".srt": "application/x-subrip",
    ".ass": "text/x-ssa",
    ".sbv": "text/plain",
    ".lrc": "text/plain",
    ".json": "application/json",
}


def _allowed_files(media: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for key in ("thumbnail", "video", "info_json"):
        value = media.get(key)
        if isinstance(value, str) and value:
            allowed.add(value)
    for sub in media.get("subtitles") or []:
        if isinstance(sub, dict) and sub.get("file"):
            allowed.add(sub["file"])
    return allowed


def _safe_media_path(base: str, file: str) -> str | None:
    """Resolve a stored relative path to an absolute file, guarding traversal.

    Returns ``None`` when the joined path escapes ``MEDIA_ROOT``.
    """
    candidate = os.path.normpath(os.path.join(MEDIA_ROOT, base, file))
    root = os.path.normpath(MEDIA_ROOT)
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


@router.get("/media/{content_id}/{file}")
async def serve_content_media(
    content_id: UUID,
    file: str,
    auth: CurrentAuth,
    db: DatabaseSession,
) -> FileResponse:
    # Media is referenced from <img>/<video> tags, which cannot send the
    # X-Workspace-Id header, so we authenticate the user and assert the content
    # belongs to one of their active workspaces rather than relying on the
    # header. The unguessable content UUID is the only capability needed.
    member_workspace_ids = {
        membership.workspace_id
        for membership in auth.user.memberships
        if membership.status == "active"
        and getattr(membership.workspace, "status", "active") == "active"
    }
    content = await db.scalar(
        select(ContentItem).where(ContentItem.id == content_id)
    )
    if (
        content is None
        or content.workspace_id not in member_workspace_ids
    ):
        raise HTTPException(status_code=404, detail="media not found")
    media = content.media
    if not isinstance(media, dict):
        raise HTTPException(status_code=404, detail="media not found")

    # The requested filename must be one we explicitly recorded for this
    # content — never an arbitrary path — to avoid serving stray files.
    if file not in _allowed_files(media):
        raise HTTPException(status_code=404, detail="media not found")

    base = media.get("base")
    if not isinstance(base, str) or not base:
        raise HTTPException(status_code=404, detail="media not found")

    candidate = _safe_media_path(base, file)
    if candidate is None:
        raise HTTPException(status_code=400, detail="invalid media path")

    if not await anyio.to_thread.run_sync(os.path.isfile, candidate):
        raise HTTPException(status_code=404, detail="media file missing")

    ext = os.path.splitext(file)[1].lower()
    media_type = _EXT_CONTENT_TYPE.get(ext, "application/octet-stream")
    return FileResponse(candidate, media_type=media_type, filename=file)
