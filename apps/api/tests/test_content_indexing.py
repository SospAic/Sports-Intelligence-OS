"""Coverage for the content -> embedding indexing pipeline.

分两层：
* 纯函数（字幕轨挑选 / 分块组合）——无 IO，快。
* ``ContentIndexingService``——跑真实 Postgres + pgvector，验证幂等（第二次不
  重复调用 embedding 后端）与陈旧块清理。
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_engine_and_session
from app.models.embedding import ContentEmbedding
from app.models.monitoring import Account, ContentItem
from app.services.content_indexing import (
    ContentIndexingService,
    build_chunks,
    select_subtitle_track,
)
from app.services.embedding import EmbeddingError, EmbeddingService

from .conftest import PG_ASYNC_URL, PG_SYNC_URL, TEST_PLATFORM_ID, TEST_REDIS_URL

_DIM = 1024


def fake_embed(text: str) -> list[float]:
    """Deterministic bag-of-characters vector.

    不追求语义质量，只要求"字面越接近，余弦距离越小"，足以驱动检索排序断言。
    """

    vector = [0.0] * _DIM
    for char in text:
        vector[ord(char) % _DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class StubEmbedder(EmbeddingService):
    """Records every call so tests can prove the cache actually skips work."""

    def __init__(self, *, enabled: bool = True) -> None:
        super().__init__(
            Settings(
                embedding_backend="tei" if enabled else "none",
                embedding_dimension=_DIM,
                embedding_model="stub-model",
            )
        )
        self.batches: list[list[str]] = []

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.enabled:
            raise EmbeddingError("stub embedder disabled")
        self.batches.append(list(texts))
        return [fake_embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_texts([text])
        return vectors[0]

    @property
    def call_count(self) -> int:
        return len(self.batches)

    @property
    def embedded_texts(self) -> list[str]:
        return [text for batch in self.batches for text in batch]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_select_subtitle_track_returns_none_without_candidates() -> None:
    assert select_subtitle_track(None) is None
    assert select_subtitle_track([]) is None
    # .ass 无法被 VTT/SRT 状态机可靠解析，必须被跳过。
    assert select_subtitle_track([{"lang": "zh", "file": "a.ass"}]) is None


def test_select_subtitle_track_prefers_content_language() -> None:
    track = select_subtitle_track(
        [
            {"lang": "en", "file": "clip.en.vtt"},
            {"lang": "ja", "file": "clip.ja.vtt"},
            {"lang": "zh-Hans", "file": "clip.zh-Hans.vtt"},
        ],
        preferred_language="zh-hans",
    )
    assert track is not None
    assert track["file"] == "clip.zh-Hans.vtt"


def test_select_subtitle_track_falls_back_to_chinese_then_english() -> None:
    zh = select_subtitle_track(
        [{"lang": "ja", "file": "a.ja.srt"}, {"lang": "zh", "file": "a.zh.srt"}]
    )
    assert zh is not None and zh["file"] == "a.zh.srt"

    en = select_subtitle_track(
        [{"lang": "ja", "file": "a.ja.srt"}, {"lang": "en", "file": "a.en.srt"}]
    )
    assert en is not None and en["file"] == "a.en.srt"


def test_select_subtitle_track_prefers_manual_over_auto() -> None:
    track = select_subtitle_track(
        [
            {"lang": "en-auto", "file": "a.en-auto.vtt"},
            {"lang": "en", "file": "a.en.vtt"},
        ]
    )
    assert track is not None
    assert track["file"] == "a.en.vtt"


def test_build_chunks_meta_only() -> None:
    chunks = build_chunks(
        title="世锦赛跳水决赛",
        description="全场回放与技术解析。",
        tags=["跳水", "世锦赛"],
        max_chars=200,
        overlap_chars=0,
        max_chunks=10,
    )
    assert [chunk.kind for chunk in chunks] == ["meta"]
    assert "世锦赛跳水决赛" in chunks[0].chunk.text
    assert "标签：跳水、世锦赛" in chunks[0].chunk.text
    assert chunks[0].chunk.start_ms is None


def test_build_chunks_includes_subtitle_with_time_range() -> None:
    subtitle = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n最后一跳完成反超。\n\n"
        "00:00:03.000 --> 00:00:06.000\n裁判打出满分。\n"
    )
    chunks = build_chunks(
        title="决赛集锦",
        description=None,
        tags=None,
        subtitle_text=subtitle,
        subtitle_ref="ws/a/vid/clip.zh.vtt",
        max_chars=200,
        overlap_chars=0,
        max_chunks=10,
    )
    kinds = [chunk.kind for chunk in chunks]
    assert kinds == ["meta", "subtitle"]
    subtitle_chunk = chunks[1]
    assert subtitle_chunk.chunk.start_ms == 1000
    assert subtitle_chunk.chunk.end_ms == 6000
    assert subtitle_chunk.source_ref == "ws/a/vid/clip.zh.vtt"
    assert "最后一跳完成反超" in subtitle_chunk.chunk.text


def test_build_chunks_reserves_budget_for_meta() -> None:
    long_subtitle = "WEBVTT\n\n" + "".join(
        f"00:00:{index:02d}.000 --> 00:00:{index + 1:02d}.000\n第{index}句解说内容。\n\n"
        for index in range(0, 50)
    )
    chunks = build_chunks(
        title="标题",
        description=None,
        tags=None,
        subtitle_text=long_subtitle,
        max_chars=40,
        overlap_chars=0,
        max_chunks=3,
    )
    assert len(chunks) == 3
    assert chunks[0].kind == "meta"


def test_build_chunks_rejects_zero_budget() -> None:
    with pytest.raises(ValueError, match="max_chunks"):
        build_chunks(
            title="x", description=None, tags=None, max_chars=10, overlap_chars=0, max_chunks=0
        )


# ---------------------------------------------------------------------------
# Service (real database)
# ---------------------------------------------------------------------------


def _seed_rows(database_path: str) -> tuple[UUID, UUID, UUID]:
    """Insert workspace/platform/account/content and return their ids."""

    from app.core.security import hash_password
    from app.models.monitoring import Platform
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMembership

    workspace_id = uuid4()
    account_id = uuid4()
    content_id = uuid4()
    now = datetime.now(UTC)

    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="索引工作区",
                slug=f"index-{workspace_id.hex[:8]}",
                status="active",
                default_timezone="Asia/Shanghai",
                row_version=1,
            )
        )
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                email_normalized=f"{user_id.hex[:8]}@example.com",
                email_display=f"{user_id.hex[:8]}@example.com",
                password_hash=hash_password("correct-horse-battery-staple"),
                display_name="索引用户",
                status="active",
                locale="zh-CN",
                timezone="Asia/Shanghai",
            )
        )
        session.add(
            WorkspaceMembership(
                id=uuid4(),
                workspace_id=workspace_id,
                user_id=user_id,
                role="owner",
                status="active",
                joined_at=now,
            )
        )
        if session.get(Platform, TEST_PLATFORM_ID) is None:
            session.add(
                Platform(
                    id=TEST_PLATFORM_ID,
                    key="test_platform",
                    name="Test Platform",
                    category="test",
                    enabled=True,
                    adapter_key="youtube_browser",
                    capabilities={},
                )
            )
        session.add(
            Account(
                id=account_id,
                workspace_id=workspace_id,
                platform_id=TEST_PLATFORM_ID,
                external_id=f"acct-{account_id.hex[:8]}",
                username="indexer",
                display_name="索引账号",
                is_active=True,
                metadata_json={},
                source_kind="imported",
                source_provider="test_fixture",
                fetched_at=now,
            )
        )
        session.add(
            ContentItem(
                id=content_id,
                workspace_id=workspace_id,
                platform_id=TEST_PLATFORM_ID,
                account_id=account_id,
                external_id=f"content-{content_id.hex[:8]}",
                content_type="video",
                title="世锦赛跳水决赛回放",
                description="最后一跳完成反超，裁判给出满分。",
                published_at=now,
                duration_seconds=120,
                canonical_url=f"https://example.com/{content_id.hex}",
                language="zh-CN",
                status="published",
                metadata_json={},
                tags=["跳水", "世锦赛"],
                first_seen_at=now,
                last_seen_at=now,
                source_kind="imported",
                source_provider="test_fixture",
                fetched_at=now,
            )
        )
        session.commit()
    engine.dispose()
    return workspace_id, account_id, content_id


@pytest.fixture
async def indexing_session(database_path: str) -> AsyncIterator[AsyncSession]:
    settings = Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
    )
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


async def test_index_item_writes_chunks_and_is_idempotent(
    indexing_session: AsyncSession, database_path: str
) -> None:
    _, _, content_id = _seed_rows(database_path)
    embedder = StubEmbedder()
    service = ContentIndexingService(indexing_session, embedder=embedder)

    item = await indexing_session.scalar(select(ContentItem).where(ContentItem.id == content_id))
    assert item is not None

    first = await service.index_item(item)
    await indexing_session.commit()
    assert first.status == "indexed"
    assert first.written == 1
    assert embedder.call_count == 1

    stored = (
        await indexing_session.scalars(
            select(ContentEmbedding).where(ContentEmbedding.content_item_id == content_id)
        )
    ).all()
    assert len(stored) == 1
    row = stored[0]
    assert row.chunk_kind == "meta"
    assert row.chunk_index == 0
    assert row.dimension == _DIM
    assert row.model == "stub-model"
    assert len(row.embedding) == _DIM
    assert "世锦赛跳水决赛回放" in row.text

    # 第二次跑：文本没变 -> 完全不调用后端。
    second = await service.index_item(item)
    await indexing_session.commit()
    assert second.status == "unchanged"
    assert second.skipped == 1
    assert embedder.call_count == 1


async def test_index_item_reembeds_after_text_change(
    indexing_session: AsyncSession, database_path: str
) -> None:
    _, _, content_id = _seed_rows(database_path)
    embedder = StubEmbedder()
    service = ContentIndexingService(indexing_session, embedder=embedder)

    item = await indexing_session.scalar(select(ContentItem).where(ContentItem.id == content_id))
    assert item is not None
    await service.index_item(item)
    await indexing_session.commit()

    item.description = "改判之后成绩被推翻。"
    await indexing_session.flush()

    outcome = await service.index_item(item)
    await indexing_session.commit()
    assert outcome.status == "indexed"
    assert outcome.written == 1
    assert embedder.call_count == 2
    assert "改判之后成绩被推翻" in embedder.embedded_texts[-1]

    total = await indexing_session.scalar(
        select(func.count(ContentEmbedding.id)).where(
            ContentEmbedding.content_item_id == content_id
        )
    )
    assert total == 1


async def test_index_item_drops_stale_chunks_when_text_shrinks(
    indexing_session: AsyncSession, database_path: str
) -> None:
    _, _, content_id = _seed_rows(database_path)
    embedder = StubEmbedder()
    settings = Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        # 必须 >= 100（生产约束 embedding_chunk_chars ge=100）；用 120 既合规又能
        # 把这段较长描述切成多块，从而验证"文本变短后多余尾块被删除"。
        embedding_chunk_chars=120,
        embedding_chunk_overlap_chars=0,
    )
    service = ContentIndexingService(indexing_session, settings, embedder=embedder)

    item = await indexing_session.scalar(select(ContentItem).where(ContentItem.id == content_id))
    assert item is not None
    item.description = "。".join(f"第{index}段解说内容都很长" for index in range(12))
    await indexing_session.flush()

    first = await service.index_item(item)
    await indexing_session.commit()
    assert first.written >= 2

    item.description = "只剩一句话。"
    await indexing_session.flush()
    second = await service.index_item(item)
    await indexing_session.commit()

    assert second.deleted >= 1
    remaining = (
        await indexing_session.scalars(
            select(ContentEmbedding.chunk_index).where(
                ContentEmbedding.content_item_id == content_id
            )
        )
    ).all()
    assert sorted(remaining) == list(range(len(remaining)))


async def test_index_item_reports_disabled_backend(
    indexing_session: AsyncSession, database_path: str
) -> None:
    _, _, content_id = _seed_rows(database_path)
    service = ContentIndexingService(indexing_session, embedder=StubEmbedder(enabled=False))
    item = await indexing_session.scalar(select(ContentItem).where(ContentItem.id == content_id))
    assert item is not None
    outcome = await service.index_item(item)
    assert outcome.status == "disabled"
    assert outcome.written == 0


async def test_index_item_reads_subtitle_from_media(
    indexing_session: AsyncSession,
    database_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, content_id = _seed_rows(database_path)
    monkeypatch.setattr("app.services.content_indexing.MEDIA_ROOT", str(tmp_path))
    base_dir = tmp_path / "ws" / "acct" / "vid"
    base_dir.mkdir(parents=True)
    (base_dir / "clip.zh.vtt").write_text(
        "WEBVTT\n\n00:00:02.000 --> 00:00:05.000\n他在最后一跳完成反超。\n",
        encoding="utf-8",
    )

    item = await indexing_session.scalar(select(ContentItem).where(ContentItem.id == content_id))
    assert item is not None
    item.media = {
        "base": "ws/acct/vid",
        "subtitles": [{"lang": "zh", "file": "clip.zh.vtt"}],
    }
    await indexing_session.flush()

    embedder = StubEmbedder()
    outcome = await ContentIndexingService(indexing_session, embedder=embedder).index_item(item)
    await indexing_session.commit()

    assert outcome.status == "indexed"
    kinds = (
        await indexing_session.scalars(
            select(ContentEmbedding.chunk_kind).where(
                ContentEmbedding.content_item_id == content_id
            )
        )
    ).all()
    assert set(kinds) == {"meta", "subtitle"}

    subtitle_row = await indexing_session.scalar(
        select(ContentEmbedding).where(
            ContentEmbedding.content_item_id == content_id,
            ContentEmbedding.chunk_kind == "subtitle",
        )
    )
    assert subtitle_row is not None
    assert subtitle_row.start_ms == 2000
    assert subtitle_row.end_ms == 5000
    assert subtitle_row.source_ref == "ws/acct/vid/clip.zh.vtt"


async def test_index_item_ignores_subtitle_outside_media_root(
    indexing_session: AsyncSession,
    database_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, content_id = _seed_rows(database_path)
    monkeypatch.setattr("app.services.content_indexing.MEDIA_ROOT", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    (tmp_path / "secret.zh.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n机密内容。\n", encoding="utf-8"
    )

    item = await indexing_session.scalar(select(ContentItem).where(ContentItem.id == content_id))
    assert item is not None
    item.media = {
        "base": "../",
        "subtitles": [{"lang": "zh", "file": "secret.zh.vtt"}],
    }
    await indexing_session.flush()

    await ContentIndexingService(indexing_session, embedder=StubEmbedder()).index_item(item)
    await indexing_session.commit()

    kinds = (
        await indexing_session.scalars(
            select(ContentEmbedding.chunk_kind).where(
                ContentEmbedding.content_item_id == content_id
            )
        )
    ).all()
    assert set(kinds) == {"meta"}
