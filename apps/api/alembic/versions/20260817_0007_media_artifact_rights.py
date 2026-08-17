"""Add an auditable media artifact rights review table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260817_0007"
down_revision = "20260817_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_artifact_rights",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("rights_status", sa.String(length=32), nullable=False),
        sa.Column("license_type", sa.String(length=120), nullable=True),
        sa.Column("rights_holder", sa.String(length=255), nullable=True),
        sa.Column("territories", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "rights_status IN ('unknown', 'pending_review', 'approved', 'restricted', 'expired')",
            name="media_rights_status",
        ),
        sa.CheckConstraint(
            "source_kind IN ('live', 'imported')", name="media_rights_source_kind"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["media_artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", name="uq_media_artifact_rights_artifact"),
    )
    op.create_index(
        "ix_media_rights_workspace_id", "media_artifact_rights", ["workspace_id"]
    )
    op.create_index(
        "ix_media_rights_artifact_id", "media_artifact_rights", ["artifact_id"]
    )
    op.create_index(
        "ix_media_rights_workspace_status",
        "media_artifact_rights",
        ["workspace_id", "rights_status"],
    )
    op.create_index(
        "ix_media_rights_workspace_expiry",
        "media_artifact_rights",
        ["workspace_id", "valid_until"],
    )
    op.alter_column("media_artifact_rights", "created_at", server_default=None)
    op.alter_column("media_artifact_rights", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_media_rights_workspace_expiry", table_name="media_artifact_rights")
    op.drop_index("ix_media_rights_workspace_status", table_name="media_artifact_rights")
    op.drop_index("ix_media_rights_artifact_id", table_name="media_artifact_rights")
    op.drop_index("ix_media_rights_workspace_id", table_name="media_artifact_rights")
    op.drop_table("media_artifact_rights")
