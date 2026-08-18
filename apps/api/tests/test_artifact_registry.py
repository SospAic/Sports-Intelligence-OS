"""Physical media integrity checks for the manifest compatibility layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.artifact import MediaArtifact
from app.services import artifact_registry


def test_manifest_items_covers_all_supported_artifact_slots() -> None:
    items = list(
        artifact_registry._manifest_items(
            {
                "base": "workspace/account/video-1",
                "video": "video-1.mp4",
                "thumbnail": "video-1.jpg",
                "info_json": "video-1.info.json",
                "subtitles": [{"lang": "en", "file": "video-1.en.vtt"}],
                "subtitle_exports": [{"lang": "zh", "file": "video-1.zh.srt"}],
            }
        )
    )

    assert {(item["kind"], item["file"]) for item in items} == {
        ("video", "video-1.mp4"),
        ("thumbnail", "video-1.jpg"),
        ("info_json", "video-1.info.json"),
        ("subtitle", "video-1.en.vtt"),
        ("subtitle_export", "video-1.zh.srt"),
    }


@pytest.mark.asyncio
async def test_inspect_file_distinguishes_ready_missing_and_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_registry, "MEDIA_ROOT", str(tmp_path))
    media_dir = tmp_path / "workspace" / "account" / "video-1"
    media_dir.mkdir(parents=True)
    video = media_dir / "video-1.mp4"
    video.write_bytes(b"deterministic media bytes")

    ready = await artifact_registry._inspect_file(
        "workspace/account/video-1/video-1.mp4", previous=None
    )
    missing = await artifact_registry._inspect_file(
        "workspace/account/video-1/missing.vtt", previous=None
    )
    escaped = await artifact_registry._inspect_file("../outside.mp4", previous=None)

    assert ready["status"] == "ready"
    assert ready["size_bytes"] == len(b"deterministic media bytes")
    assert ready["sha256"]
    assert ready["mime_type"] == "video/mp4"
    assert missing["status"] == "missing"
    assert escaped["status"] == "corrupt"


@pytest.mark.asyncio
async def test_inspect_file_reuses_checksum_when_file_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_registry, "MEDIA_ROOT", str(tmp_path))
    media_dir = tmp_path / "work"
    media_dir.mkdir()
    subtitle = media_dir / "caption.vtt"
    subtitle.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n", encoding="utf-8")

    first = await artifact_registry._inspect_file("work/caption.vtt", previous=None)
    previous = MediaArtifact(
        size_bytes=first["size_bytes"],
        file_mtime_ns=first["file_mtime_ns"],
        sha256=first["sha256"],
    )
    second = await artifact_registry._inspect_file("work/caption.vtt", previous=previous)

    assert first["status"] == second["status"] == "ready"
    assert second["sha256"] == first["sha256"]
    assert second["mime_type"] == "text/vtt"
