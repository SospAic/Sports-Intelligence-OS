"""Track physical media files independently from JSON manifests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260814_0001"
down_revision = "20260813_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=True),
        sa.Column("download_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("format", sa.String(length=16), nullable=True),
        sa.Column("file_name", sa.String(length=1024), nullable=False),
        sa.Column("relative_path", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_mtime_ns", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("mime_type", sa.String(length=160), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=False, server_default="live"),
        sa.Column("source_provider", sa.String(length=120), nullable=False, server_default="media"),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'missing', 'corrupt', 'failed', 'stale')",
            name="media_artifact_status",
        ),
        sa.CheckConstraint(
            "content_item_id IS NOT NULL OR download_id IS NOT NULL",
            name="media_artifact_owner_required",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["download_id"], ["downloads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("media_artifacts", "status", server_default=None)
    op.alter_column("media_artifacts", "source_kind", server_default=None)
    op.alter_column("media_artifacts", "source_provider", server_default=None)
    op.alter_column("media_artifacts", "metadata", server_default=None)
    op.create_index("ix_media_artifacts_workspace_status", "media_artifacts", ["workspace_id", "status"])
    op.create_index("ix_media_artifacts_content_kind", "media_artifacts", ["content_item_id", "artifact_kind"])
    op.create_index("ix_media_artifacts_download_kind", "media_artifacts", ["download_id", "artifact_kind"])
    op.create_index("ix_media_artifacts_workspace_id", "media_artifacts", ["workspace_id"])
    op.create_index("ix_media_artifacts_content_item_id", "media_artifacts", ["content_item_id"])
    op.create_index("ix_media_artifacts_download_id", "media_artifacts", ["download_id"])
    op.create_index("ix_media_artifacts_status", "media_artifacts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_media_artifacts_status", table_name="media_artifacts")
    op.drop_index("ix_media_artifacts_download_id", table_name="media_artifacts")
    op.drop_index("ix_media_artifacts_content_item_id", table_name="media_artifacts")
    op.drop_index("ix_media_artifacts_workspace_id", table_name="media_artifacts")
    op.drop_index("ix_media_artifacts_download_kind", table_name="media_artifacts")
    op.drop_index("ix_media_artifacts_content_kind", table_name="media_artifacts")
    op.drop_index("ix_media_artifacts_workspace_status", table_name="media_artifacts")
    op.drop_table("media_artifacts")
