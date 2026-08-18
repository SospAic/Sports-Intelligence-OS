"""Add observation-only content experiment records."""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0009"
down_revision = "20260817_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('draft', 'running', 'completed', 'archived')", name="content_experiment_status"),
        sa.CheckConstraint("dimension IN ('title', 'hook', 'story_order', 'thumbnail')", name="content_experiment_dimension"),
        sa.CheckConstraint("source_kind IN ('live', 'imported', 'mock')", name="content_experiment_source_kind"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_experiments_workspace_id", "content_experiments", ["workspace_id"])
    op.create_index("ix_content_experiments_created_by", "content_experiments", ["created_by"])
    op.create_index("ix_content_experiments_status", "content_experiments", ["status"])
    op.create_index("ix_content_experiments_workspace_status", "content_experiments", ["workspace_id", "status"])

    op.create_table(
        "content_experiment_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content_item_id", sa.Uuid(), nullable=True),
        sa.Column("publication_id", sa.Uuid(), nullable=True),
        sa.Column("exposure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["experiment_id"], ["content_experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "label", name="uq_content_experiment_variant_label"),
    )
    op.create_index("ix_content_experiment_variants_workspace_id", "content_experiment_variants", ["workspace_id"])
    op.create_index("ix_content_experiment_variants_experiment_id", "content_experiment_variants", ["experiment_id"])
    op.create_index("ix_content_experiment_variants_publication", "content_experiment_variants", ["publication_id"])


def downgrade() -> None:
    op.drop_table("content_experiment_variants")
    op.drop_table("content_experiments")
