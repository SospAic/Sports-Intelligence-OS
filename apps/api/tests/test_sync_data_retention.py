"""Regression tests for non-destructive account-sync enrichment."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.monitoring import Account, Comment, CommentSnapshot, ContentItem, Platform
from app.models.workspace import Workspace
from app.services.monitoring import MonitoringService
from app.services.sync import merge_media_manifest

from .conftest import PG_ASYNC_URL, TEST_PLATFORM_ID


def test_media_manifest_empty_observation_preserves_archived_files() -> None:
    existing = {
        "base": "workspace/account/video-1",
        "video": "video-1.mp4",
        "thumbnail": "video-1.jpg",
        "info_json": "video-1.info.json",
        "subtitles": [{"lang": "en", "file": "video-1.en.vtt"}],
    }

    merged = merge_media_manifest(
        existing,
        {
            "base": "workspace/account/other-base",
            "video": "",
            "subtitles": [],
        },
    )

    assert merged == existing


def test_media_manifest_adds_new_tracks_without_duplicate_or_loss() -> None:
    existing = {
        "base": "workspace/account/video-1",
        "subtitles": [{"lang": "en", "file": "video-1.en.vtt"}],
    }

    merged = merge_media_manifest(
        existing,
        {
            "subtitles": [
                {"lang": "en", "file": "video-1.en.vtt", "kind": "manual"},
                {"lang": "zh", "file": "video-1.zh.vtt", "kind": "translated"},
            ]
        },
    )

    assert merged is not None
    assert merged["subtitles"] == [
        {"lang": "en", "file": "video-1.en.vtt", "kind": "manual"},
        {"lang": "zh", "file": "video-1.zh.vtt", "kind": "translated"},
    ]


@pytest.mark.asyncio
async def test_empty_comment_refresh_preserves_existing_comment(
    client, database_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A throttled/empty top-comments response must not delete stored comments."""

    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with maker() as session:
        platform = await session.scalar(select(Platform).where(Platform.id == TEST_PLATFORM_ID))
        assert platform is not None
        workspace_id = await session.scalar(select(Workspace.id).limit(1))
        assert workspace_id is not None
        account = Account(
            id=uuid4(),
            workspace_id=workspace_id,
            platform_id=platform.id,
            external_id="retention-account",
            display_name="Retention account",
            is_active=True,
            sync_status="success",
            source_kind="live",
            source_provider="test",
            fetched_at=now,
        )
        content = ContentItem(
            id=uuid4(),
            workspace_id=workspace_id,
            platform_id=platform.id,
            account_id=account.id,
            external_id="retention-video",
            content_type="video",
            title="Retention video",
            canonical_url="https://www.youtube.com/watch?v=retention-video",
            status="published",
            metadata_json={},
            first_seen_at=now,
            last_seen_at=now,
            source_kind="live",
            source_provider="youtube_browser",
            fetched_at=now,
            source_url="https://www.youtube.com/watch?v=retention-video",
            tags=[],
        )
        comment = Comment(
            id=uuid4(),
            workspace_id=workspace_id,
            content_item_id=content.id,
            platform_comment_id="comment-1",
            author_name="Known author",
            text="Previously captured comment",
            like_count=42,
            reply_count=3,
            published_at=now,
            fetched_at=now,
            source_kind="live",
            source_provider="youtube_browser",
            source_url=content.source_url,
            metadata_json={},
        )
        session.add_all([account, content, comment])
        await session.commit()

        monkeypatch.setattr(
            "app.services.monitoring._supports_yt_dlp_comments", lambda _url: True
        )

        async def empty_comments(*_args, **_kwargs):
            return []

        monkeypatch.setattr(
            "app.services.monitoring.YtDlpAdapter.extract_comments", empty_comments
        )
        stored = await MonitoringService(session).collect_content_comments(content.id, config={})
        await session.refresh(comment)

        assert stored == 0
        assert comment.text == "Previously captured comment"
        assert comment.like_count == 42
        assert (content.metadata_json["comment_sync"]["status"]) == "empty"

    await engine.dispose()


@pytest.mark.asyncio
async def test_comment_refresh_writes_append_only_ranked_snapshots(
    client, database_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with maker() as session:
        platform = await session.scalar(select(Platform).where(Platform.id == TEST_PLATFORM_ID))
        workspace_id = await session.scalar(select(Workspace.id).limit(1))
        assert platform is not None and workspace_id is not None
        account = Account(
            id=uuid4(),
            workspace_id=workspace_id,
            platform_id=platform.id,
            external_id="snapshot-account",
            display_name="Snapshot account",
            is_active=True,
            sync_status="success",
            source_kind="live",
            source_provider="test",
            fetched_at=now,
        )
        content = ContentItem(
            id=uuid4(),
            workspace_id=workspace_id,
            platform_id=platform.id,
            account_id=account.id,
            external_id="snapshot-video",
            content_type="video",
            title="Snapshot video",
            canonical_url="https://www.youtube.com/watch?v=snapshot-video",
            status="published",
            metadata_json={},
            first_seen_at=now,
            last_seen_at=now,
            source_kind="live",
            source_provider="youtube_browser",
            fetched_at=now,
            source_url="https://www.youtube.com/watch?v=snapshot-video",
            tags=[],
        )
        session.add_all([account, content])
        await session.commit()
        monkeypatch.setattr(
            "app.services.monitoring._supports_yt_dlp_comments", lambda _url: True
        )

        async def comments(*_args, **_kwargs):
            return [
                {
                    "platform_comment_id": "snapshot-comment",
                    "author_name": "Author",
                    "text": "Great play",
                    "like_count": 12,
                    "reply_count": 2,
                    "published_at": now,
                }
            ]

        monkeypatch.setattr("app.services.monitoring.YtDlpAdapter.extract_comments", comments)
        stored = await MonitoringService(session).collect_content_comments(content.id, config={})
        snapshots = list(
            (
                await session.scalars(
                    select(CommentSnapshot).where(
                        CommentSnapshot.content_item_id == content.id
                    )
                )
            ).all()
        )

        assert stored == 1
        assert len(snapshots) == 1
        assert snapshots[0].rank == 1
        assert snapshots[0].like_count == 12
        assert snapshots[0].metadata_json["collection_id"]

    await engine.dispose()
