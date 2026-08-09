"""Regression tests: an incomplete row must never downgrade a stored work.

The fast listing path (flat catalogue enumerate + parallel per-video detail)
can produce rows built purely from the cheap catalogue read — a real title and
a real view count, but no description, no publish timestamp, no duration. That
happens in two situations:

* ``flat_known``  — the work is already stored and the policy skips it, so we
  deliberately never paid for the full extraction;
* ``flat_only``   — we *wanted* the full extraction but the per-video call
  failed, and we keep the truthful catalogue row instead of dropping the work.

Under the refresh policy (``skip_existing=False``) the upsert overwrites the
stored columns. Without protection, a single failed detail extraction would
blank out a description and publish date that an earlier full extraction had
already captured — silent data loss on every sync. The adapter therefore flags
such rows with ``metadata['partial']`` and the sync engine downgrades them to
fill-the-blanks semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import AdapterCallContext, PlatformContentData
from app.adapters.platforms.yt_dlp import YouTubeYtDlpAdapter
from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, ContentItem, Platform
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL

OBSERVED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _ctx() -> AdapterCallContext:
    return AdapterCallContext(config={}, observed_at=OBSERVED_AT, request_id="req-partial")


# -- adapter level ---------------------------------------------------------


def test_full_rows_are_not_flagged_partial() -> None:
    """A complete extraction must stay authoritative for overwrites."""
    adapter = YouTubeYtDlpAdapter()

    data = adapter._entry_to_content(
        {
            "id": "v1",
            "title": "full title",
            "description": "full description",
            "timestamp": 1_700_000_000,
            "_sio_detail_level": "full",
        },
        "handle",
        _ctx(),
    )

    assert "partial" not in data.metadata
    assert data.description == "full description"


def test_catalogue_only_rows_are_flagged_partial() -> None:
    """flat_only / flat_known rows carry the marker the sync engine reads."""
    adapter = YouTubeYtDlpAdapter()

    for level in ("flat_only", "flat_known"):
        data = adapter._entry_to_content(
            {"id": "v1", "title": "flat title", "view_count": 10, "_sio_detail_level": level},
            "handle",
            _ctx(),
        )
        assert data.metadata["partial"] is True, level
        assert data.metadata["detail_level"] == level
        # Still truthful about what it *did* read.
        assert data.title == "flat title"
        assert data.description is None


def test_rows_without_the_marker_default_to_full() -> None:
    """The legacy single-shot path emits entries with no marker at all."""
    adapter = YouTubeYtDlpAdapter()

    data = adapter._entry_to_content(
        {"id": "v1", "title": "legacy", "description": "legacy description"}, "handle", _ctx()
    )

    assert "partial" not in data.metadata


# -- sync level ------------------------------------------------------------


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )


def _content_data(*, partial: bool, status: str | None = None) -> PlatformContentData:
    metadata: dict[str, object] = {"method": "yt_dlp", "yt_view_count": 999}
    if partial:
        metadata |= {"partial": True, "detail_level": "flat_only"}
    return PlatformContentData(
        external_id="vid-1",
        account_external_id="external-001",
        content_type="video",
        title="refreshed title",
        description=None,
        published_at=None,
        duration_seconds=None,
        canonical_url="https://example.test/watch?v=vid-1",
        cover_url=None,
        language=None,
        status=status,
        source_kind="live",
        provider="test_adapter",
        fetched_at=OBSERVED_AT,
        metadata=metadata,
        media=None,
        tags=(),
    )


async def _prepare() -> tuple[async_sessionmaker, object, object, object]:
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id, platform_id, account_id = uuid4(), uuid4(), uuid4()
    async with maker() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="ws",
                    slug=f"ws-{workspace_id.hex[:8]}",
                    status="active",
                    default_timezone="UTC",
                    row_version=1,
                ),
                Platform(
                    id=platform_id,
                    key=f"platform-{platform_id.hex[:8]}",
                    name="Test",
                    category="video",
                    enabled=True,
                    adapter_key="test_adapter",
                    capabilities={},
                ),
                Account(
                    id=account_id,
                    workspace_id=workspace_id,
                    platform_id=platform_id,
                    external_id="external-001",
                    display_name="账号",
                    source_kind="imported",
                    source_provider="manual",
                    fetched_at=OBSERVED_AT,
                ),
            ]
        )
        await session.commit()
        session.add(
            ContentItem(
                id=uuid4(),
                workspace_id=workspace_id,
                platform_id=platform_id,
                account_id=account_id,
                external_id="vid-1",
                content_type="video",
                title="original title",
                description="a rich description captured by an earlier full extraction",
                published_at=datetime(2026, 1, 2, tzinfo=UTC),
                duration_seconds=Decimal("321"),
                canonical_url="https://example.test/watch?v=vid-1",
                language="en",
                status="public",
                metadata_json={},
                first_seen_at=OBSERVED_AT,
                last_seen_at=OBSERVED_AT,
                source_kind="live",
                source_provider="test_adapter",
                fetched_at=OBSERVED_AT,
                tags=[],
            )
        )
        await session.commit()
    return maker, workspace_id, platform_id, account_id


async def test_partial_row_does_not_erase_stored_detail() -> None:
    """The core regression: a failed detail extraction must not blank the row."""
    maker, _ws, _pf, account_id = await _prepare()

    async with maker() as session:
        account = await session.get(Account, account_id)
        executor = PlatformSyncExecutor(session, ProviderRegistry(), _settings())
        content, created, skipped = await executor._upsert_content(
            account, _content_data(partial=True), skip_existing=False
        )
        await session.commit()

        assert not created and not skipped
        # Everything the catalogue genuinely knows is refreshed…
        assert content.title == "refreshed title"
        assert content.metadata_json["yt_view_count"] == 999
        # …while everything it could not read is preserved.
        assert content.description == "a rich description captured by an earlier full extraction"
        assert content.published_at == datetime(2026, 1, 2, tzinfo=UTC)
        assert content.duration_seconds == Decimal("321")
        assert content.language == "en"
        assert content.status == "public"


async def test_full_row_still_overwrites_stored_detail() -> None:
    """The protection must not turn refresh syncs into append-only.

    A genuinely complete extraction that reports "no description" is telling
    the truth (the uploader removed it) and must still be applied.
    """
    maker, _ws, _pf, account_id = await _prepare()

    async with maker() as session:
        account = await session.get(Account, account_id)
        executor = PlatformSyncExecutor(session, ProviderRegistry(), _settings())
        content, _created, _skipped = await executor._upsert_content(
            account, _content_data(partial=False, status="public"), skip_existing=False
        )
        await session.commit()

        assert content.title == "refreshed title"
        assert content.description is None
        assert content.published_at is None
        assert content.duration_seconds is None


async def test_missing_status_never_violates_the_not_null_constraint() -> None:
    """``status`` is NOT NULL, so a None from the adapter must be ignored.

    Before this guard the refresh branch assigned it unconditionally and the
    whole upsert died with a NotNullViolationError, failing the work outright.
    """
    maker, _ws, _pf, account_id = await _prepare()

    async with maker() as session:
        account = await session.get(Account, account_id)
        executor = PlatformSyncExecutor(session, ProviderRegistry(), _settings())
        content, _created, _skipped = await executor._upsert_content(
            account, _content_data(partial=False, status=None), skip_existing=False
        )
        await session.commit()

        assert content.status == "public"
