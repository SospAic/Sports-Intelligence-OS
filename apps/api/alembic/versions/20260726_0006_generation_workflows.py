"""Create versioned prompts and auditable generation workflows.

Revision ID: 20260726_0006
Revises: 20260726_0005
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0006"
down_revision: str | None = "20260726_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled', 'archived')", name="prompt_collection_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "key"),
    )
    for name, columns in (
        ("ix_prompt_collections_workspace_id", ["workspace_id"]),
        ("ix_prompt_collections_current_version_id", ["current_version_id"]),
        ("ix_prompt_collections_workspace_status", ["workspace_id", "status"]),
    ):
        op.create_index(name, "prompt_collections", columns)

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("variables_schema", sa.JSON(), nullable=False),
        sa.Column("model_config", sa.JSON(), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="prompt_version_status"),
        sa.ForeignKeyConstraint(["collection_id"], ["prompt_collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "version"),
    )
    for name, columns in (
        ("ix_prompt_versions_workspace_id", ["workspace_id"]),
        ("ix_prompt_versions_collection_id", ["collection_id"]),
        ("ix_prompt_versions_created_by", ["created_by"]),
        ("ix_prompt_versions_collection_status", ["collection_id", "status"]),
        ("ix_prompt_versions_workspace_created", ["workspace_id", "created_at"]),
    ):
        op.create_index(name, "prompt_versions", columns)

    op.create_table(
        "generation_workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_types", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("default_rule_set_version_id", sa.Uuid(), nullable=True),
        sa.Column("default_prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["default_prompt_version_id"], ["prompt_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["default_rule_set_version_id"], ["rule_set_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "key"),
    )
    for name, columns in (
        ("ix_generation_workflows_workspace_id", ["workspace_id"]),
        ("ix_generation_workflows_default_rule_set_version_id", ["default_rule_set_version_id"]),
        ("ix_generation_workflows_default_prompt_version_id", ["default_prompt_version_id"]),
        ("ix_generation_workflows_workspace_enabled", ["workspace_id", "enabled"]),
    ):
        op.create_index(name, "generation_workflows", columns)

    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("input_type", sa.String(32), nullable=False),
        sa.Column("input_id", sa.Uuid(), nullable=True),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("rule_set_version_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("model_config", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_step", sa.String(80), nullable=True),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.Column("final_output", sa.JSON(), nullable=True),
        sa.Column("validation_result", sa.JSON(), nullable=False),
        sa.Column("rewrite_count", sa.Integer(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_saved", sa.Boolean(), nullable=False),
        sa.Column("user_rating", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="generation_run_status"),
        sa.CheckConstraint("rewrite_count >= 0", name="generation_run_rewrite_count"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_version_id"], ["rule_set_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_id"], ["generation_workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    for name, columns in (
        ("ix_generation_runs_workspace_id", ["workspace_id"]),
        ("ix_generation_runs_created_by", ["created_by"]),
        ("ix_generation_runs_workflow_id", ["workflow_id"]),
        ("ix_generation_runs_input_type", ["input_type"]),
        ("ix_generation_runs_input_id", ["input_id"]),
        ("ix_generation_runs_input_hash", ["input_hash"]),
        ("ix_generation_runs_rule_set_version_id", ["rule_set_version_id"]),
        ("ix_generation_runs_prompt_version_id", ["prompt_version_id"]),
        ("ix_generation_runs_provider", ["provider"]),
        ("ix_generation_runs_status", ["status"]),
        ("ix_generation_runs_workspace_created", ["workspace_id", "created_at"]),
        ("ix_generation_runs_workspace_status", ["workspace_id", "status"]),
    ):
        op.create_index(name, "generation_runs", columns)

    op.create_table(
        "generation_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("prompt_snapshot", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'skipped')", name="generation_step_status"),
        sa.ForeignKeyConstraint(["run_id"], ["generation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_key"),
    )
    op.create_index("ix_generation_steps_workspace_id", "generation_steps", ["workspace_id"])
    op.create_index("ix_generation_steps_run_id", "generation_steps", ["run_id"])
    op.create_index("ix_generation_steps_run_order", "generation_steps", ["run_id", "sort_order"])


def downgrade() -> None:
    op.drop_table("generation_steps")
    op.drop_table("generation_runs")
    op.drop_table("generation_workflows")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_collections")
