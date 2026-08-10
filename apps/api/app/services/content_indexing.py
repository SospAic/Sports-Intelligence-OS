"""Turn ``content_items`` rows into ``content_embeddings`` rows.

职责边界
--------
* **纯函数部分**（``select_subtitle_track`` / ``build_chunks``）不碰数据库也不碰
  磁盘，可以被单测完整覆盖。
* **IO 部分**（``ContentIndexingService``）负责读字幕文件、调用 embedding 后端、
  幂等写库。

幂等性
------
每个块都存了 ``text_hash``。重跑索引时先把该内容已有的 ``(chunk_kind, chunk_index)``
读出来比对哈希：内容没变就跳过（不发网络请求），变了才重新嵌入并原地更新，
源文本变短导致的多余尾块则删除。这样即便对 9000 条内容反复回填，第二次也几乎
零成本。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

import anyio
from sqlalchemy import delete, func, select
from sqlalchemy import tuple_ as sa_tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.embedding import ContentEmbedding
from app.models.monitoring import ContentItem
from app.services.embedding import EmbeddingService, build_embedding_service
from app.services.text_chunking import (
    TextChunk,
    build_meta_text,
    chunk_cues,
    chunk_text,
    parse_subtitle,
)

logger = logging.getLogger(__name__)

#: 与 ``app/api/routes/media.py`` 保持同一约定：media 里存的是相对路径。
MEDIA_ROOT = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")

#: 只解析我们能可靠解析的字幕格式。``.ass`` / ``.sbv`` / ``.lrc`` 结构差异大，
#: 强行按 VTT 状态机解析会产出垃圾文本，宁可跳过。
_PARSABLE_SUBTITLE_SUFFIXES = (".vtt", ".srt")

#: 单个字幕文件的读取上限，防止异常大文件把 worker 内存打爆。
_MAX_SUBTITLE_BYTES = 4 * 1024 * 1024

#: 自动生成字幕的语言标记，例如 ``en-orig``、``zh-Hans-auto``。
_AUTO_MARKERS = ("-auto", "auto-", ".auto")


@dataclass(frozen=True, slots=True)
class PendingChunk:
    """A chunk that is ready to be embedded and persisted."""

    kind: str
    chunk: TextChunk
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class IndexOutcome:
    """Per-item result, aggregated by the Celery task into a run summary."""

    content_item_id: UUID
    status: str
    written: int = 0
    skipped: int = 0
    deleted: int = 0
    detail: str | None = None


def _normalise_lang(value: str | None) -> str:
    return (value or "").strip().lower()


def select_subtitle_track(
    subtitles: Sequence[dict[str, Any]] | None,
    *,
    preferred_language: str | None = None,
) -> dict[str, Any] | None:
    """Pick the single subtitle file worth embedding.

    一条视频常常带十几条机器翻译字幕轨。全部嵌入既贵又会让同一段话在向量库里
    重复十几次，严重污染召回排序。这里只留一条，优先级：

    1. 内容自身语言（``content_items.language``）
    2. 中文（``zh*``）
    3. 英文（``en*``）
    4. 第一条可解析的

    同优先级下人工字幕优于自动字幕（自动字幕含大量识别错误）。
    """

    if not subtitles:
        return None

    candidates: list[dict[str, Any]] = []
    for entry in subtitles:
        if not isinstance(entry, dict):
            continue
        file_name = entry.get("file")
        if not isinstance(file_name, str) or not file_name:
            continue
        if not file_name.lower().endswith(_PARSABLE_SUBTITLE_SUFFIXES):
            continue
        candidates.append(entry)
    if not candidates:
        return None

    preferred = _normalise_lang(preferred_language)

    def rank(entry: dict[str, Any]) -> tuple[int, int, str]:
        lang = _normalise_lang(entry.get("lang"))
        if preferred and (lang == preferred or lang.startswith(preferred + "-")):
            priority = 0
        elif lang.startswith("zh"):
            priority = 1
        elif lang.startswith("en"):
            priority = 2
        elif lang:
            priority = 3
        else:
            priority = 4
        automatic = 1 if any(marker in lang for marker in _AUTO_MARKERS) else 0
        return (priority, automatic, lang)

    return min(candidates, key=rank)


def build_chunks(
    *,
    title: str | None,
    description: str | None,
    tags: Sequence[str] | None,
    subtitle_text: str | None = None,
    subtitle_ref: str | None = None,
    max_chars: int,
    overlap_chars: int,
    max_chunks: int,
) -> list[PendingChunk]:
    """Compose every embeddable chunk for one content item.

    ``meta`` 块永远优先占用配额：即便字幕很长，标题/描述也必须进索引，否则
    没有字幕的内容（当前线上 100%）就完全搜不到。
    """

    if max_chunks <= 0:
        raise ValueError("max_chunks must be positive")

    pending: list[PendingChunk] = []

    meta_text = build_meta_text(title=title, description=description, tags=tags)
    if meta_text:
        for chunk in chunk_text(
            meta_text,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            max_chunks=max_chunks,
        ):
            pending.append(PendingChunk(kind="meta", chunk=chunk))

    remaining = max_chunks - len(pending)
    if subtitle_text and remaining > 0:
        cues = parse_subtitle(subtitle_text)
        subtitle_chunks = chunk_cues(
            cues,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            max_chunks=remaining,
        )
        for chunk in subtitle_chunks:
            pending.append(PendingChunk(kind="subtitle", chunk=chunk, source_ref=subtitle_ref))

    return pending


class ContentIndexingService:
    """Reads content, embeds it, and keeps ``content_embeddings`` in sync."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        embedder: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._embedder = embedder or build_embedding_service(self._settings)

    @property
    def embedder(self) -> EmbeddingService:
        return self._embedder

    async def index_item(self, item: ContentItem) -> IndexOutcome:
        """Index (or refresh) a single content item."""

        if not self._embedder.enabled:
            return IndexOutcome(
                content_item_id=item.id,
                status="disabled",
                detail="embedding backend is 'none'",
            )

        subtitle_text, subtitle_ref = await self._load_subtitle(item)
        pending = build_chunks(
            title=item.title,
            description=item.description,
            tags=list(item.tags or []),
            subtitle_text=subtitle_text,
            subtitle_ref=subtitle_ref,
            max_chars=self._settings.embedding_chunk_chars,
            overlap_chars=self._settings.embedding_chunk_overlap_chars,
            max_chunks=self._settings.embedding_max_chunks_per_item,
        )

        model = self._embedder.model
        existing = await self._load_existing(item.id, model)

        if not pending:
            deleted = await self._delete_keys(item.id, model, set(existing))
            return IndexOutcome(
                content_item_id=item.id,
                status="empty",
                deleted=deleted,
            )

        # 按 kind 重新编号，让 (kind, index) 在一条内容内唯一且连续。
        numbered: list[PendingChunk] = []
        counters: dict[str, int] = {}
        for entry in pending:
            index = counters.get(entry.kind, 0)
            counters[entry.kind] = index + 1
            numbered.append(replace(entry, chunk=replace(entry.chunk, index=index)))

        stale = [
            key for key in existing if key[0] not in counters or key[1] >= counters.get(key[0], 0)
        ]
        deleted = await self._delete_keys(item.id, model, set(stale))

        changed = [
            entry
            for entry in numbered
            if existing.get((entry.kind, entry.chunk.index)) != entry.chunk.text_hash
        ]
        if not changed:
            return IndexOutcome(
                content_item_id=item.id,
                status="unchanged",
                skipped=len(numbered),
                deleted=deleted,
            )

        vectors = await self._embedder.embed_texts([entry.chunk.text for entry in changed])
        await self._persist(item, model, changed, vectors)

        return IndexOutcome(
            content_item_id=item.id,
            status="indexed",
            written=len(changed),
            skipped=len(numbered) - len(changed),
            deleted=deleted,
        )

    async def _load_existing(self, item_id: UUID, model: str) -> dict[tuple[str, int], str]:
        rows = await self._session.execute(
            select(
                ContentEmbedding.chunk_kind,
                ContentEmbedding.chunk_index,
                ContentEmbedding.text_hash,
            ).where(
                ContentEmbedding.content_item_id == item_id,
                ContentEmbedding.model == model,
            )
        )
        return {(kind, index): text_hash for kind, index, text_hash in rows.all()}

    async def _delete_keys(self, item_id: UUID, model: str, keys: set[tuple[str, int]]) -> int:
        if not keys:
            return 0
        # One bulk DELETE instead of N per-key round-trips: during a large
        # backfill the stale-chunk set can be large, and the per-key loop was a
        # measurable source of round-trips.
        result = await self._session.execute(
            delete(ContentEmbedding).where(
                ContentEmbedding.content_item_id == item_id,
                ContentEmbedding.model == model,
                sa_tuple(ContentEmbedding.chunk_kind, ContentEmbedding.chunk_index).in_(keys),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def _persist(
        self,
        item: ContentItem,
        model: str,
        entries: Sequence[PendingChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        rows = await self._session.execute(
            select(ContentEmbedding).where(
                ContentEmbedding.content_item_id == item.id,
                ContentEmbedding.model == model,
            )
        )
        by_key = {(row.chunk_kind, row.chunk_index): row for row in rows.scalars().all()}

        for entry, vector in zip(entries, vectors, strict=True):
            key = (entry.kind, entry.chunk.index)
            record = by_key.get(key)
            if record is None:
                record = ContentEmbedding(
                    workspace_id=item.workspace_id,
                    content_item_id=item.id,
                    model=model,
                    dimension=self._embedder.dimension,
                    chunk_kind=entry.kind,
                    chunk_index=entry.chunk.index,
                    text=entry.chunk.text,
                    text_hash=entry.chunk.text_hash,
                    start_ms=entry.chunk.start_ms,
                    end_ms=entry.chunk.end_ms,
                    source_ref=entry.source_ref,
                    embedding=list(vector),
                )
                self._session.add(record)
                continue
            record.dimension = self._embedder.dimension
            record.text = entry.chunk.text
            record.text_hash = entry.chunk.text_hash
            record.start_ms = entry.chunk.start_ms
            record.end_ms = entry.chunk.end_ms
            record.source_ref = entry.source_ref
            record.embedding = list(vector)
        await self._session.flush()

    async def _load_subtitle(self, item: ContentItem) -> tuple[str | None, str | None]:
        media = item.media
        if not isinstance(media, dict):
            return None, None
        base = media.get("base")
        if not isinstance(base, str) or not base:
            return None, None
        track = select_subtitle_track(media.get("subtitles"), preferred_language=item.language)
        if track is None:
            return None, None
        relative = os.path.join(base, str(track["file"]))
        # normpath 只做纯字符串规范化（折叠 ../），不触盘；真正的读文件在
        # anyio.to_thread 里做。os.path 的 ASYNC240 在这里是误报。
        path = os.path.normpath(os.path.join(MEDIA_ROOT, relative))  # noqa: ASYNC240
        root = os.path.normpath(MEDIA_ROOT)  # noqa: ASYNC240
        if path != root and not path.startswith(root + os.sep):
            logger.warning("subtitle_path_escapes_media_root", extra={"path": relative})
            return None, None
        try:
            content = await anyio.to_thread.run_sync(_read_text_file, path)
        except OSError as exc:
            logger.warning(
                "subtitle_read_failed",
                extra={"path": relative, "error": str(exc)},
            )
            return None, None
        if content is None:
            return None, None
        return content, relative


def _read_text_file(path: str) -> str | None:
    """Read a subtitle file, tolerating the encodings yt-dlp emits."""

    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) > _MAX_SUBTITLE_BYTES:
        logger.warning("subtitle_too_large", extra={"path": path})
        return None
    with open(path, "rb") as handle:
        raw = handle.read()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


async def count_indexable_items(session: AsyncSession, workspace_id: UUID | None) -> int:
    """How many content items currently have text worth embedding."""

    statement = select(func.count(ContentItem.id)).where(
        func.coalesce(func.nullif(func.trim(ContentItem.title), ""), None).isnot(None)
    )
    if workspace_id is not None:
        statement = statement.where(ContentItem.workspace_id == workspace_id)
    return int(await session.scalar(statement) or 0)
