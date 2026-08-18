"""End-to-end path-traversal protection for the two file-serving routes.

The review checklist (项目全面审查清单-2026-08-06.md, line 133) flagged that
``tests/`` covered ``/avatar`` but not the traversal guards on
``GET /api/v1/media/{content_id}/{file}`` (``serve_content_media``) and
``GET /api/v1/downloads/{download_id}/file/{file}`` (``download_file``).

Those routes already apply defense-in-depth:

* ``file`` must be one of the filenames we explicitly recorded for that row
  (``_allowed_files``) — otherwise 404;
* the joined path is resolved through ``_safe_media_path`` and rejected (400)
  if it would escape ``MEDIA_ROOT``.

These tests prove the *HTTP layer* honours that: a valid recorded file is
served (200) while an encoded traversal payload is never served (404/400,
and the response body is never the target file's contents).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.download import Download
from app.models.monitoring import ContentItem

from .conftest import PG_SYNC_URL, TEST_PLATFORM_ID
from .test_monitoring_api import authenticate, create_account

# Encoded "../" so the test client does not normalise it away before the
# request reaches the route (the route sees the decoded "../../etc/passwd").
_TRAVERSAL = "%2e%2e%2f" * 6 + "etc%2fpasswd"


def _seed_content(client: TestClient, media: dict) -> tuple[UUID, UUID]:
    csrf_token = authenticate(client)
    account = create_account(client, csrf_token)
    account_id = UUID(account["id"])
    workspace_id = UUID(account["workspace_id"])
    now = datetime.now(UTC)
    content_id = uuid4()
    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        session.add(
            ContentItem(
                id=content_id,
                workspace_id=workspace_id,
                platform_id=TEST_PLATFORM_ID,
                account_id=account_id,
                external_id=f"content-{content_id.hex[:8]}",
                content_type="video",
                title="穿越测试作品",
                description="",
                published_at=now - timedelta(days=1),
                duration_seconds=30.0,
                canonical_url=f"https://example.com/{content_id.hex}",
                cover_url=None,
                language="zh-CN",
                status="published",
                metadata_json={},
                first_seen_at=now - timedelta(days=1),
                last_seen_at=now,
                source_kind="imported",
                source_provider="test_fixture",
                fetched_at=now,
                source_url=f"https://example.com/{content_id.hex}",
                media=media,
            )
        )
        session.commit()
    return content_id, workspace_id


def _seed_download(workspace_id: UUID, media: dict) -> UUID:
    now = datetime.now(UTC)
    download_id = uuid4()
    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        session.add(
            Download(
                id=download_id,
                workspace_id=workspace_id,
                url="https://example.com/video",
                platform="youtube",
                status="completed",
                media=media,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return download_id


def test_serve_content_media_serves_recorded_file_but_blocks_traversal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    # A legitimately recorded file sitting under the content's base dir.
    base_dir = tmp_path / "ws" / "h" / "vid"
    base_dir.mkdir(parents=True)
    (base_dir / "clip.mp4").write_bytes(b"REAL-CONTENT-BYTES")

    content_id, _ = _seed_content(client, {"video": "clip.mp4", "base": "ws/h/vid"})

    # Valid recorded file is served.
    ok = client.get(f"/api/v1/media/{content_id}/clip.mp4")
    assert ok.status_code == 200, ok.text
    assert ok.content == b"REAL-CONTENT-BYTES"

    # Traversal payload must NOT serve /etc/passwd.
    bad = client.get(f"/api/v1/media/{content_id}/{_TRAVERSAL}")
    assert bad.status_code in (400, 404), bad.text
    assert b"root:" not in bad.content


def test_download_file_serves_recorded_file_but_blocks_traversal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    base_dir = tmp_path / "ws" / "dl" / "id"
    base_dir.mkdir(parents=True)
    (base_dir / "dl.mp4").write_bytes(b"REAL-DOWNLOAD-BYTES")

    csrf_token = authenticate(client)
    account = create_account(client, csrf_token)
    workspace_id = UUID(account["workspace_id"])
    download_id = _seed_download(workspace_id, {"video": "dl.mp4", "base": "ws/dl/id"})

    headers = {"X-CSRF-Token": csrf_token, "X-Workspace-Id": str(workspace_id)}
    ok = client.get(f"/api/v1/downloads/{download_id}/file/dl.mp4", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.content == b"REAL-DOWNLOAD-BYTES"

    bad = client.get(f"/api/v1/downloads/{download_id}/file/{_TRAVERSAL}", headers=headers)
    assert bad.status_code in (400, 404), bad.text
    assert b"root:" not in bad.content
