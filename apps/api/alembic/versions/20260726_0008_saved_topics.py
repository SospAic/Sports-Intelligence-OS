"""Add auditable saved topic library.

Revision ID: 20260726_0008
Revises: 20260726_0007
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0008"
down_revision: str | None = "20260726_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            "source_type IN ('content', 'article', 'event', 'manual')",
            name="saved_topic_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('inbox', 'planned', 'in_progress', 'completed', 'archived')",
            name="saved_topic_status",
        ),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="saved_topic_priority"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "source_type", "source_id"),
    )
    for name, columns in (
        ("ix_saved_topics_workspace_id", ["workspace_id"]),
        ("ix_saved_topics_created_by", ["created_by"]),
        ("ix_saved_topics_source_type", ["source_type"]),
        ("ix_saved_topics_source_id", ["source_id"]),
        ("ix_saved_topics_status", ["status"]),
        ("ix_saved_topics_workspace_status", ["workspace_id", "status", "created_at"]),
    ):
        op.create_index(name, "saved_topics", columns)


def downgrade() -> None:
    op.drop_table("saved_topics")
