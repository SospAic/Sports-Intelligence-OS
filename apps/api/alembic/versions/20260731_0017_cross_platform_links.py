"""Add cross_platform_links table for cross-platform same-topic clustering.

Stores suggested links between entities on different platforms. Links require
human confirmation before being treated as the same factual event — the system
never auto-merges cross-language similar titles.

Revision ID: 20260731_0017
Revises: 20260730_0016
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260731_0017"
down_revision: str | None = "20260730_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cross_platform_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_entity_type", sa.String(50), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(), nullable=False),
        sa.Column("target_entity_type", sa.String(50), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="suggested"),
        sa.Column("match_details", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected')",
            name="cross_platform_link_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="cross_platform_link_confidence_range",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cpl_workspace_status",
        "cross_platform_links",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_cpl_source",
        "cross_platform_links",
        ["source_entity_type", "source_entity_id"],
    )
    op.create_index(
        "ix_cpl_target",
        "cross_platform_links",
        ["target_entity_type", "target_entity_id"],
    )
    op.create_index(
        "ix_cross_platform_links_workspace_id",
        "cross_platform_links",
        ["workspace_id"],
    )
    op.create_index(
        "ix_cross_platform_links_status",
        "cross_platform_links",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_cross_platform_links_status", table_name="cross_platform_links")
    op.drop_index("ix_cross_platform_links_workspace_id", table_name="cross_platform_links")
    op.drop_index("ix_cpl_target", table_name="cross_platform_links")
    op.drop_index("ix_cpl_source", table_name="cross_platform_links")
    op.drop_index("ix_cpl_workspace_status", table_name="cross_platform_links")
    op.drop_table("cross_platform_links")
