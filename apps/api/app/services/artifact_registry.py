"""Reconcile media manifests with physical files on the media volume.

Adapters continue to write the compact JSON manifest for compatibility.  This
service is the single place that decides whether a referenced file is actually
available and usable enough for a download/playback button to claim success.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from stat import S_ISREG
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import MediaArtifact

MEDIA_ROOT = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")
MAX_HASH_BYTES = int(os.environ.get("SIO_ARTIFACT_MAX_HASH_BYTES", str(512 * 1024 * 1024)))


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_relative(base: str, filename: str) -> str | None:
    """Join manifest components while rejecting absolute/path-traversal input."""

    if not base.strip() or not filename.strip():
        return None
    base_path = Path(base)
    file_path = Path(filename)
    if base_path.is_absolute() or file_path.is_absolute():
        return None
    relative = Path(os.path.normpath(os.path.join(base, filename)))
    if relative == Path(".") or ".." in relative.parts:
        return None
    return relative.as_posix()


def _manifest_items(media: Mapping[str, Any] | None) -> Iterable[dict[str, Any]]:
    if not isinstance(media, Mapping):
        return []
    base = str(media.get("base") or "").strip()
    if not base:
        return []
    scalar_kinds = {
        "video": "video",
        "audio": "audio",
        "thumbnail": "thumbnail",
        "info_json": "info_json",
    }
    items: list[dict[str, Any]] = []
    for key, kind in scalar_kinds.items():
        filename = media.get(key)
        if isinstance(filename, str) and filename.strip():
            items.append({"kind": kind, "file": filename, "language": None, "source": media})
    for key, kind in (
        ("subtitles", "subtitle"),
        ("subtitle_exports", "subtitle_export"),
        ("subtitle_artifacts", "subtitle"),
    ):
        values = media.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, Mapping):
                continue
            filename = value.get("file")
            if not isinstance(filename, str) or not filename.strip():
                continue
            items.append(
                {
                    "kind": kind,
                    "file": filename,
                    "language": (
                        str(value.get("lang") or value.get("language") or "").strip() or None
                    ),
                    "source": dict(value),
                }
            )
    return items


def _mime_type(filename: str) -> str | None:
    if filename.casefold().endswith(".vtt"):
        return "text/vtt"
    if filename.casefold().endswith(".srt"):
        return "application/x-subrip"
    return mimetypes.guess_type(filename)[0]


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_path(relative_path: str) -> str | None:
    root = os.path.abspath(MEDIA_ROOT)
    candidate = os.path.abspath(os.path.join(root, relative_path))
    return candidate if os.path.commonpath((root, candidate)) == root else None


async def _inspect_file(
    relative_path: str,
    *,
    previous: MediaArtifact | None,
) -> dict[str, Any]:
    candidate = _artifact_path(relative_path)
    if candidate is None:
        return {
            "status": "corrupt",
            "size_bytes": None,
            "file_mtime_ns": None,
            "sha256": None,
            "mime_type": None,
            "error_detail": "artifact path escapes media root",
        }
    try:
        stat = await asyncio.to_thread(os.stat, candidate)
    except FileNotFoundError:
        return {
            "status": "missing",
            "size_bytes": None,
            "file_mtime_ns": None,
            "sha256": None,
            "mime_type": _mime_type(os.path.basename(candidate)),
            "error_detail": "physical file does not exist",
        }
    except OSError as exc:
        return {
            "status": "failed",
            "size_bytes": None,
            "file_mtime_ns": None,
            "sha256": None,
            "mime_type": _mime_type(os.path.basename(candidate)),
            "error_detail": str(exc)[:500],
        }
    if not S_ISREG(stat.st_mode) or stat.st_size <= 0:
        return {
            "status": "corrupt",
            "size_bytes": int(stat.st_size),
            "file_mtime_ns": int(stat.st_mtime_ns),
            "sha256": None,
            "mime_type": _mime_type(os.path.basename(candidate)),
            "error_detail": "artifact is not a non-empty regular file",
        }
    sha256 = None
    if (
        previous is not None
        and previous.size_bytes == stat.st_size
        and previous.file_mtime_ns == stat.st_mtime_ns
        and previous.sha256
    ):
        sha256 = previous.sha256
    elif stat.st_size <= MAX_HASH_BYTES:
        sha256 = await asyncio.to_thread(_sha256, str(candidate))
    return {
        "status": "ready",
        "size_bytes": int(stat.st_size),
        "file_mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256,
        "mime_type": _mime_type(os.path.basename(candidate)),
        "error_detail": None,
    }


async def reconcile_manifest(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    media: Mapping[str, Any] | None,
    content_item_id: UUID | None = None,
    download_id: UUID | None = None,
    source_kind: str = "live",
    source_provider: str = "media",
    source_url: str | None = None,
    commit: bool = True,
) -> list[MediaArtifact]:
    """Upsert and physically inspect every file in a media manifest."""

    if content_item_id is None and download_id is None:
        raise ValueError("an artifact owner is required")
    owner_filter = [MediaArtifact.workspace_id == workspace_id]
    if content_item_id is not None:
        owner_filter.append(MediaArtifact.content_item_id == content_item_id)
    if download_id is not None:
        owner_filter.append(MediaArtifact.download_id == download_id)
    existing_rows = list((await session.scalars(select(MediaArtifact).where(*owner_filter))).all())
    by_key = {
        (row.artifact_kind, row.language or "", row.format or "", row.file_name): row
        for row in existing_rows
    }
    output: list[MediaArtifact] = []
    for item in _manifest_items(media):
        filename = str(item["file"])
        relative_path = _safe_relative(str(media.get("base") or ""), filename)  # type: ignore[union-attr]
        kind = str(item["kind"])
        language = item.get("language")
        fmt = Path(filename).suffix.casefold().lstrip(".") or None
        key = (kind, str(language or ""), str(fmt or ""), filename)
        row = by_key.get(key)
        if row is None:
            row = MediaArtifact(
                workspace_id=workspace_id,
                content_item_id=content_item_id,
                download_id=download_id,
                artifact_kind=kind,
                language=language,
                format=fmt,
                file_name=filename,
                relative_path=relative_path or filename,
                status="pending",
                retention_class="temporary" if download_id is not None else "managed",
            )
            session.add(row)
        row.relative_path = relative_path or filename
        row.source_kind = source_kind
        row.source_provider = source_provider
        row.source_url = source_url
        row.metadata_json = dict(item.get("source") or {})
        inspected = await _inspect_file(row.relative_path, previous=row)
        for field, value in inspected.items():
            setattr(row, field, value)
        row.checked_at = _now()
        output.append(row)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return output


async def list_content_artifacts(
    session: AsyncSession, workspace_id: UUID, content_item_id: UUID
) -> list[MediaArtifact]:
    return list(
        (
            await session.scalars(
                select(MediaArtifact)
                .where(
                    MediaArtifact.workspace_id == workspace_id,
                    MediaArtifact.content_item_id == content_item_id,
                )
                .order_by(MediaArtifact.artifact_kind.asc(), MediaArtifact.file_name.asc())
            )
        ).all()
    )
