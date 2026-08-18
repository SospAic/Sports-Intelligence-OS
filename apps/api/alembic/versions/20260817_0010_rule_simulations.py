"""Add auditable rule applicability simulations and feedback."""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0010"
down_revision = "20260817_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_simulation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("historical_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("applicable_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["rule_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["rule_set_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_simulation_runs_workspace_id", "rule_simulation_runs", ["workspace_id"])
    op.create_index("ix_rule_simulation_runs_rule_set_id", "rule_simulation_runs", ["rule_set_id"])
    op.create_index("ix_rule_simulation_runs_version_id", "rule_simulation_runs", ["version_id"])
    op.create_index("ix_rule_simulation_runs_created_by", "rule_simulation_runs", ["created_by"])
    op.create_index(
        "ix_rule_simulation_runs_workspace_created",
        "rule_simulation_runs",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_rule_simulation_runs_version_created",
        "rule_simulation_runs",
        ["version_id", "created_at"],
    )

    op.create_table(
        "rule_simulation_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("simulation_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "verdict IN ('pass', 'fail', 'not_applicable', 'uncertain')",
            name="rule_simulation_feedback_verdict",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["simulation_id"], ["rule_simulation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "simulation_id",
            "rule_id",
            "created_by",
            name="uq_rule_simulation_feedback_actor_rule",
        ),
    )
    op.create_index("ix_rule_simulation_feedback_workspace_id", "rule_simulation_feedback", ["workspace_id"])
    op.create_index("ix_rule_simulation_feedback_simulation_id", "rule_simulation_feedback", ["simulation_id"])
    op.create_index("ix_rule_simulation_feedback_rule_id", "rule_simulation_feedback", ["rule_id"])
    op.create_index("ix_rule_simulation_feedback_created_by", "rule_simulation_feedback", ["created_by"])
    op.create_index(
        "ix_rule_simulation_feedback_simulation",
        "rule_simulation_feedback",
        ["simulation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("rule_simulation_feedback")
    op.drop_table("rule_simulation_runs")
