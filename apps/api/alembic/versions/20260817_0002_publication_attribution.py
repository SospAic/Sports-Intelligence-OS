"""Add publication records and fixed-window performance attribution."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260817_0002"
down_revision = "20260817_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=True),
        sa.Column("editorial_item_id", sa.Uuid(), nullable=True),
        sa.Column("content_item_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("platform_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('planned', 'scheduled', 'published', 'unverified', 'failed', 'cancelled')",
            name="publication_status",
        ),
        sa.CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name="publication_source_kind",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["editorial_item_id"], ["editorial_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "platform_id",
            "external_id",
            name="uq_publications_workspace_platform_external",
        ),
    )
    op.create_index(
        "ix_publications_workspace_id", "publications", ["workspace_id"]
    )
    op.create_index("ix_publications_created_by", "publications", ["created_by"])
    op.create_index("ix_publications_generation_run_id", "publications", ["generation_run_id"])
    op.create_index("ix_publications_editorial_item_id", "publications", ["editorial_item_id"])
    op.create_index("ix_publications_content_item_id", "publications", ["content_item_id"])
    op.create_index("ix_publications_account_id", "publications", ["account_id"])
    op.create_index("ix_publications_platform_id", "publications", ["platform_id"])
    op.create_index("ix_publications_status", "publications", ["status"])
    op.create_index(
        "ix_publications_workspace_status_time",
        "publications",
        ["workspace_id", "status", "published_at"],
    )
    op.create_index(
        "ix_publications_workspace_content", "publications", ["workspace_id", "content_item_id"]
    )
    op.create_index(
        "ix_publications_workspace_generation", "publications", ["workspace_id", "generation_run_id"]
    )
    op.alter_column("publications", "created_at", server_default=None)
    op.alter_column("publications", "updated_at", server_default=None)

    op.create_table(
        "performance_attributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("window_key", sa.String(length=8), nullable=False),
        sa.Column("window_seconds", sa.BigInteger(), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measurement_status", sa.String(length=24), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.BigInteger(), nullable=True),
        sa.Column("share_count", sa.BigInteger(), nullable=True),
        sa.Column("favorite_count", sa.BigInteger(), nullable=True),
        sa.Column("follower_gain", sa.BigInteger(), nullable=True),
        sa.Column("average_watch_time", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("completion_rate", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=True),
        sa.Column("source_provider", sa.String(length=120), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "window_key IN ('1h', '3h', '6h', '24h', '72h', '7d', '30d')",
            name="performance_attribution_window_key",
        ),
        sa.CheckConstraint(
            "measurement_status IN ('measured', 'not_due', 'unavailable')",
            name="performance_attribution_measurement_status",
        ),
        sa.CheckConstraint(
            "source_kind IS NULL OR source_kind IN ('live', 'imported', 'mock')",
            name="performance_attribution_source_kind",
        ),
        sa.CheckConstraint("view_count IS NULL OR view_count >= 0", name="performance_attribution_views_nonnegative"),
        sa.CheckConstraint("like_count IS NULL OR like_count >= 0", name="performance_attribution_likes_nonnegative"),
        sa.CheckConstraint("comment_count IS NULL OR comment_count >= 0", name="performance_attribution_comments_nonnegative"),
        sa.CheckConstraint("share_count IS NULL OR share_count >= 0", name="performance_attribution_shares_nonnegative"),
        sa.CheckConstraint("favorite_count IS NULL OR favorite_count >= 0", name="performance_attribution_favorites_nonnegative"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id", "window_key", name="uq_performance_attribution_publication_window"
        ),
    )
    op.create_index(
        "ix_performance_attributions_workspace_id",
        "performance_attributions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_performance_attributions_publication_id",
        "performance_attributions",
        ["publication_id"],
    )
    op.create_index(
        "ix_performance_attribution_publication_window",
        "performance_attributions",
        ["publication_id", "window_seconds"],
    )
    op.create_index(
        "ix_performance_attribution_workspace_captured",
        "performance_attributions",
        ["workspace_id", "captured_at"],
    )
    op.alter_column("performance_attributions", "created_at", server_default=None)
    op.alter_column("performance_attributions", "updated_at", server_default=None)


def downgrade() -> None:
    for index_name in (
        "ix_performance_attribution_workspace_captured",
        "ix_performance_attribution_publication_window",
        "ix_performance_attributions_publication_id",
        "ix_performance_attributions_workspace_id",
    ):
        op.drop_index(index_name, table_name="performance_attributions")
    op.drop_table("performance_attributions")
    for index_name in (
        "ix_publications_workspace_generation",
        "ix_publications_workspace_content",
        "ix_publications_workspace_status_time",
        "ix_publications_status",
        "ix_publications_platform_id",
        "ix_publications_account_id",
        "ix_publications_content_item_id",
        "ix_publications_editorial_item_id",
        "ix_publications_generation_run_id",
        "ix_publications_created_by",
        "ix_publications_workspace_id",
    ):
        op.drop_index(index_name, table_name="publications")
    op.drop_table("publications")
