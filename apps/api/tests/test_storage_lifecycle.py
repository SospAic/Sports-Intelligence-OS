"""Safety and retention tests for the explicit media lifecycle policy."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.models.artifact import MediaArtifact
from app.services import artifact_registry
from app.services.storage import _safe_delete, _scan_workspace_files, media_lifecycle


def test_workspace_scan_is_bounded_and_excludes_other_workspaces(tmp_path: Path) -> None:
    workspace_id = uuid4()
    own = tmp_path / str(workspace_id) / "account" / "video.mp4"
    other = tmp_path / str(uuid4()) / "account" / "other.mp4"
    own.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    own.write_bytes(b"video")
    other.write_bytes(b"other")

    scanned, truncated, files = _scan_workspace_files(str(tmp_path), workspace_id, 10)

    assert scanned == 1
    assert truncated is False
    assert list(files) == [f"{workspace_id}/account/video.mp4"]


def test_safe_delete_rejects_symlink_and_path_escape(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"data")
    link = tmp_path / "link.bin"
    link.symlink_to(target)

    with pytest.raises(FileNotFoundError):
        _safe_delete(str(tmp_path), "link.bin")
    with pytest.raises(FileNotFoundError):
        _safe_delete(str(tmp_path), "../target.bin")
    assert target.exists()


def _fake_session(artifacts: list[MediaArtifact]) -> MagicMock:
    session = MagicMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: artifacts))
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_lifecycle_dry_run_never_deletes_temporary_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = uuid4()
    monkeypatch.setattr(artifact_registry, "MEDIA_ROOT", str(tmp_path))
    path = tmp_path / str(workspace_id) / "downloads" / "old.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old media")
    old = datetime.now(UTC) - timedelta(days=45)
    os.utime(path, (old.timestamp(), old.timestamp()))
    artifact = MediaArtifact(
        id=uuid4(),
        workspace_id=workspace_id,
        download_id=uuid4(),
        artifact_kind="video",
        file_name="old.mp4",
        relative_path=f"{workspace_id}/downloads/old.mp4",
        status="ready",
        retention_class="temporary",
        size_bytes=9,
        file_mtime_ns=path.stat().st_mtime_ns,
        created_at=old,
        updated_at=old,
    )
    session = _fake_session([artifact])
    settings = Settings(
        environment="test",
        media_retention_days=30,
        media_lifecycle_enabled=False,
        media_lifecycle_dry_run=True,
    )

    report = await media_lifecycle(session, settings, workspace_id)

    assert report.dry_run is True
    assert report.deleted_file_count == 0
    assert len(report.candidates) == 1
    assert path.exists()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifecycle_explicit_execution_marks_tracked_artifact_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = uuid4()
    monkeypatch.setattr(artifact_registry, "MEDIA_ROOT", str(tmp_path))
    path = tmp_path / str(workspace_id) / "downloads" / "old.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old media")
    old = datetime.now(UTC) - timedelta(days=45)
    os.utime(path, (old.timestamp(), old.timestamp()))
    artifact = MediaArtifact(
        id=uuid4(),
        workspace_id=workspace_id,
        download_id=uuid4(),
        artifact_kind="video",
        file_name="old.mp4",
        relative_path=f"{workspace_id}/downloads/old.mp4",
        status="ready",
        retention_class="temporary",
        size_bytes=9,
        file_mtime_ns=path.stat().st_mtime_ns,
        created_at=old,
        updated_at=old,
    )
    session = _fake_session([artifact])
    settings = Settings(
        environment="test",
        media_retention_days=30,
        media_lifecycle_enabled=True,
        media_lifecycle_dry_run=False,
    )

    report = await media_lifecycle(
        session, settings, workspace_id, dry_run=False, confirm=True
    )

    assert report.dry_run is False
    assert report.deleted_file_count == 1
    assert report.marked_stale_count == 1
    assert artifact.status == "stale"
    assert not path.exists()
