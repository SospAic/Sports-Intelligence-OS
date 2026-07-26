"""Add encrypted workspace LLM provider settings.

Revision ID: 20260726_0009
Revises: 20260726_0008
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0009"
down_revision: str | None = "20260726_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("config_masked", sa.JSON(), nullable=False),
        sa.Column("default_model", sa.String(160), nullable=False),
        sa.Column("default_parameters", sa.JSON(), nullable=False),
        sa.Column("input_cost_per_million", sa.Numeric(18, 6), nullable=True),
        sa.Column("output_cost_per_million", sa.Numeric(18, 6), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_status", sa.String(32), nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "provider_key"),
    )
    for name, columns in (
        ("ix_llm_provider_settings_workspace_id", ["workspace_id"]),
        ("ix_llm_provider_settings_provider_key", ["provider_key"]),
        ("ix_llm_provider_settings_workspace_enabled", ["workspace_id", "enabled"]),
    ):
        op.create_index(name, "llm_provider_settings", columns)


def downgrade() -> None:
    op.drop_table("llm_provider_settings")
