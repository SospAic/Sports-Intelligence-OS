"""Serve locally-archived media (thumbnail / video / subtitles / info-json).

Files are written by download-capable adapters under ``MEDIA_ROOT`` during a
sync and referenced from ``ContentItem.media``. This endpoint resolves a stored
*relative* path, enforces workspace ownership, and guards against path
traversal before streaming the bytes back to the detail page.
"""

from __future__ import annotations

import functools
import os
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import anyio
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.dependencies import CurrentAuth, DatabaseSession
from app.models.monitoring import Account, ContentItem

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
    content = await db.scalar(select(ContentItem).where(ContentItem.id == content_id))
    if content is None or content.workspace_id not in member_workspace_ids:
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


# --- Account avatar local archive ---------------------------------------
#
# Platform avatars (especially TikTok / Douyin) are served through short-lived
# signed CDN URLs that 404 within hours, so the account list / detail pages
# render broken images. Instead of hot-linking the remote URL, we lazily cache
# the avatar on first request under ``MEDIA_ROOT/avatars`` and serve the
# permanent local copy thereafter. A miss (no avatar, or a failed fetch) returns
# 404 so the frontend can fall back to the remote URL and finally to initials.

_AVATAR_ALLOWED_EXT: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
_AVATAR_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _avatar_cache_path(account_id: UUID, avatar_url: str) -> str:
    parsed = urlparse(avatar_url)
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext not in _AVATAR_ALLOWED_EXT:
        ext = ".jpg"
    return os.path.join(MEDIA_ROOT, "avatars", f"{account_id}{ext}")


def _fetch_remote_bytes(url: str, timeout: int = 10) -> bytes:
    if urlparse(url).scheme.lower() not in {"http", "https"}:
        raise ValueError("avatar URL must use http or https")
    with httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _AVATAR_USER_AGENT},
        follow_redirects=False,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


@router.get("/accounts/{account_id}/avatar")
async def serve_account_avatar(
    account_id: UUID,
    auth: CurrentAuth,
    db: DatabaseSession,
) -> FileResponse:
    member_workspace_ids = {
        membership.workspace_id
        for membership in auth.user.memberships
        if membership.status == "active"
        and getattr(membership.workspace, "status", "active") == "active"
    }
    account = await db.scalar(select(Account).where(Account.id == account_id))
    if account is None or account.workspace_id not in member_workspace_ids:
        raise HTTPException(status_code=404, detail="avatar not found")
    avatar_url = account.avatar_url
    if not avatar_url:
        raise HTTPException(status_code=404, detail="avatar not found")

    cache_path = _avatar_cache_path(account_id, avatar_url)
    if await anyio.to_thread.run_sync(os.path.isfile, cache_path):
        ext = os.path.splitext(cache_path)[1].lower()
        return FileResponse(
            cache_path,
            media_type=_EXT_CONTENT_TYPE.get(ext, "image/jpeg"),
            filename=os.path.basename(cache_path),
        )
    try:
        data = await anyio.to_thread.run_sync(_fetch_remote_bytes, avatar_url)
    except Exception as exc:  # noqa: BLE001 - any fetch failure degrades to remote URL
        raise HTTPException(status_code=404, detail="avatar not found") from exc
    if not data:
        raise HTTPException(status_code=404, detail="avatar not found")
    avatars_dir = os.path.dirname(cache_path)
    await anyio.to_thread.run_sync(functools.partial(os.makedirs, avatars_dir, 0o755, True))
    await anyio.to_thread.run_sync(functools.partial(_write_file, cache_path, data))
    ext = os.path.splitext(cache_path)[1].lower()
    return FileResponse(
        cache_path,
        media_type=_EXT_CONTENT_TYPE.get(ext, "image/jpeg"),
        filename=os.path.basename(cache_path),
    )
