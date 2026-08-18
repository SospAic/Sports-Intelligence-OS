"""Read-only media volume and artifact health reporting."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.artifact import MediaArtifact
from app.schemas.storage import (
    StorageHealthRead,
    StorageLifecycleCandidateRead,
    StorageLifecycleRead,
)
from app.services.audit import build_audit_entry


def _scan_media_root(root: str, max_files: int) -> tuple[int, int, bool, dict[str, int]]:
    """Scan regular files without following symlinks or deleting anything."""

    root_path = Path(root)
    if not root_path.exists():
        return 0, 0, False, {}
    total_bytes = 0
    file_count = 0
    paths: dict[str, int] = {}
    for current_root, directories, filenames in os.walk(root_path, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not os.path.islink(os.path.join(current_root, name))
        ]
        for filename in filenames:
            path = os.path.join(current_root, filename)
            if os.path.islink(path):
                continue
            try:
                stat = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if not os.path.isfile(path) or stat.st_size <= 0:
                continue
            relative = os.path.relpath(path, root_path).replace(os.sep, "/")
            paths[relative] = int(stat.st_size)
            total_bytes += int(stat.st_size)
            file_count += 1
            if file_count >= max_files:
                return total_bytes, file_count, True, paths
    return total_bytes, file_count, False, paths


def _volume_usage(root: str) -> tuple[int | None, int | None]:
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return None, None
    return int(usage.total), int(usage.free)


def _workspace_prefixes(workspace_id: UUID) -> tuple[str, str]:
    value = str(workspace_id)
    return f"{value}/", f"downloads/{value}/"


def _scan_workspace_files(
    root: str, workspace_id: UUID, max_files: int
) -> tuple[int, bool, dict[str, tuple[int, datetime]]]:
    """Return regular files belonging to one workspace, without following links."""

    root_path = Path(root)
    if not root_path.exists():
        return 0, False, {}
    prefixes = _workspace_prefixes(workspace_id)
    files: dict[str, tuple[int, datetime]] = {}
    scanned = 0
    for current_root, directories, filenames in os.walk(root_path, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not os.path.islink(os.path.join(current_root, name))
        ]
        for filename in filenames:
            path = os.path.join(current_root, filename)
            if os.path.islink(path):
                continue
            relative = os.path.relpath(path, root_path).replace(os.sep, "/")
            if not relative.startswith(prefixes):
                continue
            try:
                stat = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            scanned += 1
            if stat.st_size <= 0:
                continue
            files[relative] = (
                int(stat.st_size),
                datetime.fromtimestamp(stat.st_mtime, UTC),
            )
            if scanned >= max_files:
                return scanned, True, files
    return scanned, False, files


def _artifact_age(row: MediaArtifact) -> datetime:
    if row.last_accessed_at is not None:
        return row.last_accessed_at
    if row.file_mtime_ns is not None:
        return datetime.fromtimestamp(row.file_mtime_ns / 1_000_000_000, UTC)
    if row.checked_at is not None:
        return row.checked_at
    return row.created_at


def _safe_delete(root: str, relative_path: str) -> int:
    """Delete one already-planned regular file beneath the configured root."""

    root_path = Path(root).resolve()
    unresolved = root_path / relative_path
    if unresolved.is_symlink():
        raise FileNotFoundError("planned media path is a symlink")
    candidate = unresolved.resolve()
    if root_path not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError("planned media path is no longer a regular child file")
    size = candidate.stat().st_size
    candidate.unlink()
    return int(size)


async def media_lifecycle(
    session: AsyncSession,
    settings: Settings,
    workspace_id: UUID,
    *,
    dry_run: bool = True,
    confirm: bool = False,
    actor_id: UUID | None = None,
    actor_type: str = "system",
    max_files: int | None = None,
) -> StorageLifecycleRead:
    """Plan or explicitly execute bounded media retention cleanup.

    The default is intentionally non-destructive. Even a caller requesting an
    execution is downgraded to a dry run unless the deployment enabled the
    lifecycle switch and disabled the dry-run guard. Tracked ``managed`` and
    ``protected`` artifacts are never selected by this policy.
    """

    from app.services.artifact_registry import MEDIA_ROOT

    now = datetime.now(UTC)
    limit = max_files or settings.media_lifecycle_batch_size
    scanned, scan_truncated, files = await asyncio.to_thread(
        _scan_workspace_files, MEDIA_ROOT, workspace_id, limit
    )
    artifacts = list(
        (
            await session.scalars(
                select(MediaArtifact).where(MediaArtifact.workspace_id == workspace_id)
            )
        ).all()
    )
    known_paths = {row.relative_path for row in artifacts if row.relative_path}
    orphan_cutoff = now - timedelta(days=settings.media_orphan_retention_days)
    candidates: list[StorageLifecycleCandidateRead] = []
    skipped: Counter[str] = Counter()

    for row in artifacts:
        if row.retention_class == "protected":
            skipped["protected"] += 1
            continue
        if row.retention_class == "managed":
            skipped["managed"] += 1
            continue
        if row.status != "ready":
            skipped[f"status_{row.status}"] += 1
            continue
        if row.retain_until is not None and row.retain_until > now:
            skipped["retain_until"] += 1
            continue
        eligible_at = _artifact_age(row) + timedelta(days=settings.media_retention_days)
        if eligible_at > now:
            skipped["retention_window"] += 1
            continue
        if row.relative_path not in files:
            skipped["tracked_file_not_scanned"] += 1
            continue
        candidates.append(
            StorageLifecycleCandidateRead(
                kind="tracked",
                relative_path=row.relative_path,
                size_bytes=row.size_bytes,
                reason="temporary artifact exceeded the configured retention window",
                action="delete_tracked",
                artifact_id=row.id,
                artifact_kind=row.artifact_kind,
                retention_class=row.retention_class,
                eligible_at=eligible_at,
            )
        )

    if not scan_truncated:
        for relative_path, (size_bytes, modified_at) in files.items():
            if relative_path in known_paths:
                continue
            if modified_at >= orphan_cutoff:
                skipped["orphan_grace_period"] += 1
                continue
            candidates.append(
                StorageLifecycleCandidateRead(
                    kind="orphan",
                    relative_path=relative_path,
                    size_bytes=size_bytes,
                    reason="regular workspace file is not referenced by Artifact Registry",
                    action="delete_orphan",
                    eligible_at=orphan_cutoff,
                )
            )
    else:
        skipped["orphan_scan_incomplete"] += 1

    candidates = candidates[:limit]
    effective_dry_run = (
        dry_run
        or not confirm
        or not settings.media_lifecycle_enabled
        or settings.media_lifecycle_dry_run
    )
    deleted_file_count = 0
    deleted_bytes = 0
    marked_stale_count = 0
    failures: list[dict[str, str]] = []
    if not effective_dry_run:
        for candidate in candidates:
            try:
                deleted_size = await asyncio.to_thread(
                    _safe_delete, MEDIA_ROOT, candidate.relative_path
                )
                deleted_file_count += 1
                deleted_bytes += deleted_size
                if candidate.artifact_id is not None:
                    artifact_row = next(
                        (item for item in artifacts if item.id == candidate.artifact_id), None
                    )
                    if artifact_row is not None:
                        artifact_row.status = "stale"
                        artifact_row.deleted_at = now
                        artifact_row.checked_at = now
                        artifact_row.error_detail = (
                            "removed by the configured media lifecycle policy"
                        )
                        marked_stale_count += 1
            except (FileNotFoundError, OSError) as exc:
                failures.append(
                    {"path": candidate.relative_path, "error": str(exc)[:300]}
                )

    audit = build_audit_entry(
        id=uuid4(),
        workspace_id=workspace_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="storage.lifecycle.cleanup",
        resource_type="media_storage",
        resource_id=None,
        change_summary_json={
            "dry_run": effective_dry_run,
            "automatic_cleanup_enabled": settings.media_lifecycle_enabled,
            "scanned_file_count": scanned,
            "candidate_count": len(candidates),
            "deleted_file_count": deleted_file_count,
            "deleted_bytes": deleted_bytes,
            "marked_stale_count": marked_stale_count,
            "failure_count": len(failures),
            "sample_paths": [item.relative_path for item in candidates[:20]],
        },
        reason="media retention governance",
        trace_id=uuid4(),
        created_at=now,
        status="failed" if failures else "success",
        error_code="media_lifecycle_partial_failure" if failures else None,
        error_detail=(f"{len(failures)} planned files could not be removed" if failures else None),
    )
    session.add(audit)
    await session.commit()
    return StorageLifecycleRead(
        generated_at=now,
        workspace_id=workspace_id,
        dry_run=effective_dry_run,
        automatic_cleanup_enabled=settings.media_lifecycle_enabled,
        policy={
            "retention_days": settings.media_retention_days,
            "orphan_retention_days": settings.media_orphan_retention_days,
            "batch_size": limit,
            "managed_and_protected_are_never_deleted": True,
            "scan_truncated": scan_truncated,
        },
        scanned_file_count=scanned,
        scan_truncated=scan_truncated,
        candidates=candidates,
        skipped=dict(skipped),
        deleted_file_count=deleted_file_count,
        deleted_bytes=deleted_bytes,
        marked_stale_count=marked_stale_count,
        failed=failures,
        audit_id=audit.id,
    )


async def media_health(
    session: AsyncSession,
    settings: Settings,
    workspace_id: UUID,
) -> StorageHealthRead:
    """Build a bounded storage report for one workspace."""

    from app.services.artifact_registry import MEDIA_ROOT

    _scanned, truncated, workspace_files = await asyncio.to_thread(
        _scan_workspace_files,
        MEDIA_ROOT,
        workspace_id,
        settings.media_storage_scan_max_files,
    )
    files = {path: size for path, (size, _mtime) in workspace_files.items()}
    media_bytes = sum(files.values())
    file_count = len(files)
    total_bytes, free_bytes = await asyncio.to_thread(_volume_usage, MEDIA_ROOT)
    artifacts = list(
        (
            await session.scalars(
                select(MediaArtifact).where(MediaArtifact.workspace_id == workspace_id)
            )
        ).all()
    )
    counts = Counter(str(item.status) for item in artifacts)
    known_paths = {item.relative_path for item in artifacts if item.relative_path}
    orphan_pairs = (
        [(path, size) for path, size in files.items() if path not in known_paths]
        if not truncated
        else []
    )
    quota = settings.media_storage_quota_bytes
    warnings: list[str] = []
    if truncated:
        warnings.append("storage scan reached its file limit; orphan counts are incomplete")
    if counts.get("missing", 0) or counts.get("corrupt", 0) or counts.get("failed", 0):
        warnings.append("one or more tracked artifacts are not physically ready")
    if quota is not None and media_bytes > quota:
        warnings.append("media volume exceeds the configured soft quota")
    return StorageHealthRead(
        generated_at=datetime.now(UTC),
        quota_bytes=quota,
        quota_percent=round(media_bytes / quota * 100, 2) if quota else None,
        media_bytes=media_bytes,
        media_file_count=file_count,
        scan_truncated=truncated,
        orphan_file_count=None if truncated else len(orphan_pairs),
        orphan_bytes=None if truncated else sum(size for _, size in orphan_pairs),
        volume_total_bytes=total_bytes,
        volume_free_bytes=free_bytes,
        tracked_artifact_count=len(artifacts),
        tracked_ready_count=counts.get("ready", 0),
        tracked_ready_bytes=sum(
            int(item.size_bytes or 0) for item in artifacts if item.status == "ready"
        ),
        artifact_counts=dict(counts),
        warnings=warnings,
        policy={
            "automatic_cleanup": settings.media_lifecycle_enabled
            and not settings.media_lifecycle_dry_run,
            "destructive_actions_performed": False,
            "retention_days": settings.media_retention_days,
            "orphan_retention_days": settings.media_orphan_retention_days,
            "managed_and_protected_are_never_deleted": True,
        },
    )
