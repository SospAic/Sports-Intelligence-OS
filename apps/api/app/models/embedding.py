"""pgvector-backed embeddings for locally ingested content.

设计要点
--------
* **不依赖 `pgvector` pip 包。** 本环境 pypi 长期不可达（SSLEOFError），任何新增
  第三方依赖都会让 `docker compose build api` 失败。因此这里用一个自实现的
  ``Vector`` UserDefinedType 承担 DDL 与 Python <-> 文本表示的转换，并在
  ``app/db/session.py`` 里给 asyncpg 注册一个 text-format 的 ``vector`` codec。
* **向量维度是全局常量。** 列类型在迁移里被写死成 ``vector(N)``，N 取自
  ``SIO_EMBEDDING_DIMENSION``。换模型（维度变了）必须新写一条迁移并回填，
  不能只改环境变量。
* **一条内容会产生多行。** 标题/描述/标签合成一段 ``meta`` 文本，字幕按时间轴
  切成若干 ``subtitle`` 块。命中 subtitle 块时可以借助 ``start_ms`` 直接跳到
  视频对应位置，这是纯 LLM 方案给不了的定位能力。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.core.config import get_settings
from app.db.base import Base, TimestampMixin

#: 允许的分块来源。meta = 标题+描述+标签；subtitle = 字幕轨切片；
#: transcript = 未来接入 faster-whisper 后的语音转写切片。
CHUNK_KINDS: tuple[str, ...] = ("meta", "subtitle", "transcript")


def _now() -> datetime:
    return datetime.now(UTC)


def embedding_dimension() -> int:
    """当前部署使用的向量宽度（迁移与模型必须一致）。"""

    return get_settings().embedding_dimension


class Vector(UserDefinedType[Sequence[float]]):
    """最小可用的 pgvector 列类型。

    只覆盖本项目需要的能力：DDL 渲染成 ``vector(dim)``，绑定参数把 Python
    序列序列化成 pgvector 的文本表示 ``[1,2,3]``，取回时再解析成 ``list[float]``。
    距离运算一律在 SQL 里用操作符（``<=>`` 余弦 / ``<->`` L2）显式书写。
    """

    cache_ok = True

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim

    def get_col_spec(self, **_kw: Any) -> str:
        if self.dim is None:
            return "vector"
        return f"vector({self.dim})"

    def bind_processor(self, dialect: Dialect) -> Any:
        dim = self.dim

        def process(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            values = [float(item) for item in value]
            if dim is not None and len(values) != dim:
                raise ValueError(
                    f"embedding has {len(values)} dimensions but the column expects {dim}; "
                    "the deployed model and SIO_EMBEDDING_DIMENSION are out of sync"
                )
            return "[" + ",".join(repr(item) for item in values) + "]"

        return process

    def result_processor(self, dialect: Dialect, coltype: Any) -> Any:
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list | tuple):
                return [float(item) for item in value]
            raw = str(value).strip()
            if raw.startswith("[") and raw.endswith("]"):
                raw = raw[1:-1]
            if not raw:
                return []
            return [float(part) for part in raw.split(",")]

        return process


def encode_vector(values: Iterable[float]) -> str:
    """把向量序列化成 pgvector 文本表示，供裸 SQL 参数使用。"""

    return "[" + ",".join(repr(float(item)) for item in values) + "]"


class ContentEmbedding(TimestampMixin, Base):
    """A single embedded chunk derived from a ``content_items`` row."""

    __tablename__ = "content_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "content_item_id",
            "model",
            "chunk_kind",
            "chunk_index",
            name="uq_content_embeddings_chunk",
        ),
        Index(
            "ix_content_embeddings_workspace_model",
            "workspace_id",
            "model",
        ),
        Index("ix_content_embeddings_item", "content_item_id"),
        CheckConstraint(
            "chunk_kind IN ('meta', 'subtitle', 'transcript')",
            name="content_embeddings_chunk_kind",
        ),
        CheckConstraint("chunk_index >= 0", name="content_embeddings_chunk_index"),
        CheckConstraint("char_length(text) > 0", name="content_embeddings_text_present"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    content_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(240), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: sha256 of the chunk text; lets a re-run skip chunks whose source never changed.
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 字幕块在视频里的时间区间（毫秒），非字幕块为 NULL。
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 例如字幕文件的相对路径，便于溯源。
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(embedding_dimension()), nullable=False
    )
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
