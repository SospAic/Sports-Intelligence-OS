"""Enable pgvector and add content_embeddings for local semantic retrieval.

检索链路完全本地化：向量由自托管的 embedding 服务（默认 BGE-M3）生成，
相似度在 PostgreSQL 内用 pgvector 的余弦操作符 ``<=>`` 计算，不调用任何 LLM。

注意
----
* ``vector(N)`` 的 N 取自 ``SIO_EMBEDDING_DIMENSION``（默认 1024 = BGE-M3）。
  换成别的维度的模型必须新写一条迁移重建列与索引，并重新回填。
* HNSW 索引在空表上建立是瞬时的；回填完成后如果召回质量不理想，可以调
  ``hnsw.ef_search``（会话级）而不必重建索引。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.config import get_settings
from app.models.embedding import Vector

revision: str = "20260808_0001"
down_revision: str | None = "20260806_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIMENSION = get_settings().embedding_dimension


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "content_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(240), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("chunk_kind", sa.String(32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("embedding", Vector(_DIMENSION), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_content_embeddings"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_content_embeddings_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_item_id"],
            ["content_items.id"],
            name="fk_content_embeddings_content_item_id_content_items",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "content_item_id",
            "model",
            "chunk_kind",
            "chunk_index",
            name="uq_content_embeddings_chunk",
        ),
        # 裸名即可：Base.metadata 的 naming_convention 会把它套进
        # ck_%(table_name)s_%(constraint_name)s，写成全名反而会被套两层并截断。
        sa.CheckConstraint(
            "chunk_kind IN ('meta', 'subtitle', 'transcript')",
            name="content_embeddings_chunk_kind",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="content_embeddings_chunk_index",
        ),
        sa.CheckConstraint(
            "char_length(text) > 0",
            name="content_embeddings_text_present",
        ),
    )

    op.create_index(
        "ix_content_embeddings_workspace_model",
        "content_embeddings",
        ["workspace_id", "model"],
    )
    op.create_index(
        "ix_content_embeddings_item",
        "content_embeddings",
        ["content_item_id"],
    )
    op.execute(
        "CREATE INDEX ix_content_embeddings_vector_hnsw "
        "ON content_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_embeddings_vector_hnsw")
    op.drop_index("ix_content_embeddings_item", table_name="content_embeddings")
    op.drop_index("ix_content_embeddings_workspace_model", table_name="content_embeddings")
    op.drop_table("content_embeddings")
    # 扩展保留：其它表可能已经依赖它，且删除扩展的代价远大于留着。
