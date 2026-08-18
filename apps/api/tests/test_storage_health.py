from pathlib import Path

from app.services.storage import _scan_media_root


def test_storage_scan_counts_regular_files_and_stops_at_bound(tmp_path: Path) -> None:
    (tmp_path / "workspace" / "one").mkdir(parents=True)
    (tmp_path / "workspace" / "one" / "video.mp4").write_bytes(b"1234")
    (tmp_path / "workspace" / "one" / "caption.vtt").write_text("WEBVTT", encoding="utf-8")

    total, count, truncated, paths = _scan_media_root(str(tmp_path), 10)

    assert total == 10
    assert count == 2
    assert truncated is False
    assert paths["workspace/one/video.mp4"] == 4


def test_storage_scan_reports_truncation_without_claiming_complete_orphans(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.bin").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"bb")

    total, count, truncated, paths = _scan_media_root(str(tmp_path), 1)

    assert total in {1, 2}
    assert count == 1
    assert truncated is True
    assert len(paths) == 1
