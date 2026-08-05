from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.news_seed import EXPANDED_SOURCE_EXAMPLES
from app.services.operations import _operation_error_hint


def test_successful_operation_has_no_error_hint() -> None:
    assert (
        _operation_error_hint(
            "success",
            code=None,
            message=None,
            detail=None,
            category="worker",
        )
        is None
    )
    assert (
        _operation_error_hint(
            "completed",
            code=None,
            message=None,
            detail=None,
            existing="stale hint from an older run",
        )
        is None
    )


def test_failed_operation_keeps_actionable_error_hint() -> None:
    hint = _operation_error_hint(
        "error",
        code="login_required",
        message="login wall",
        detail="adapter rejected the request",
        adapter_key="youtube_browser",
    )
    assert hint is not None
    assert "登录" in hint
    assert "youtube_browser" in hint


def test_generic_open_source_feeds_are_opt_in() -> None:
    enabled_by_default = {
        spec["name"]: spec.get("enabled", True) for spec in EXPANDED_SOURCE_EXAMPLES
    }
    assert enabled_by_default["dev.to · Data Science（开源社区，默认停用）"] is False
    assert enabled_by_default["Hacker News · Front Page（开源社区，默认停用）"] is False
    assert enabled_by_default["Hacker News · Sports（开源社区，默认停用）"] is False


def test_comment_task_runs_async_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import monitoring

    content_id = uuid4()
    called: list[object] = []

    async def fake_collect(value):
        called.append(value)
        return 3

    monkeypatch.setattr(monitoring, "_run_collect_comments", fake_collect)

    assert monitoring.collect_content_comments.run(str(content_id)) == 3
    assert called == [content_id]


def test_download_task_runs_async_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import monitoring

    download_id = uuid4()
    called: list[object] = []

    async def fake_download(value):
        called.append(value)

    monkeypatch.setattr(monitoring, "_run_download", fake_download)

    assert monitoring.download_url_task.run(str(download_id)) is None
    assert called == [download_id]


def test_profile_url_gets_compact_account_label() -> None:
    from app.services.monitoring import _display_name_from_locator

    assert _display_name_from_locator("https://www.tiktok.com/@creator") == "@creator"
    assert _display_name_from_locator("creator", username="creator") == "@creator"


def test_metadata_sync_preserves_archived_media_manifest() -> None:
    from app.services.sync import merge_media_manifest

    existing = {"video": "/media/old.mp4", "thumbnail": "/media/old.jpg"}
    assert merge_media_manifest(existing, None) == existing
    assert merge_media_manifest(existing, {"info_json": "/media/info.json"}) == {
        **existing,
        "info_json": "/media/info.json",
    }
