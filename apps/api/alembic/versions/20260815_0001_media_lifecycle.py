"""Add explicit media retention metadata for lifecycle governance."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0001"
down_revision = "20260814_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_artifacts",
        sa.Column("retention_class", sa.String(length=16), nullable=False, server_default="managed"),
    )
    op.add_column(
        "media_artifacts",
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_artifacts",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_artifacts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("media_artifacts", "retention_class", server_default=None)
    op.create_check_constraint(
        "media_artifact_retention_class",
        "media_artifacts",
        "retention_class IN ('managed', 'temporary', 'protected')",
    )
    op.create_index(
        "ix_media_artifacts_workspace_retention",
        "media_artifacts",
        ["workspace_id", "retention_class"],
    )
    # On-demand downloads are the only existing artifact family that can be
    # safely considered temporary without changing the semantics of monitored
    # content. Operators can still promote one to protected before cleanup.
    op.execute(
        sa.text(
            "UPDATE media_artifacts SET retention_class = 'temporary' "
            "WHERE download_id IS NOT NULL AND retention_class = 'managed'"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_media_artifacts_workspace_retention", table_name="media_artifacts")
    op.drop_constraint(
        "media_artifact_retention_class", "media_artifacts", type_="check"
    )
    op.drop_column("media_artifacts", "deleted_at")
    op.drop_column("media_artifacts", "last_accessed_at")
    op.drop_column("media_artifacts", "retain_until")
    op.drop_column("media_artifacts", "retention_class")
