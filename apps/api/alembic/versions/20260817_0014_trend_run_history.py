"""Persist hotspot derivative/search run history and language projections."""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0014"
down_revision = "20260817_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "derivative_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_topic_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_query", sa.String(length=500), nullable=False),
        sa.Column("source_query_en", sa.String(length=500), nullable=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column(
            "process_log",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_results",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "translations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notice", sa.String(length=2000), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["source_topic_id"], ["trend_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_derivative_run_workspace_created",
        "derivative_runs",
        ["workspace_id", "created_at"],
    )
    op.create_index("ix_derivative_run_topic", "derivative_runs", ["source_topic_id"])
    op.alter_column("derivative_runs", "process_log", server_default=None)
    op.alter_column("derivative_runs", "source_results", server_default=None)
    op.alter_column("derivative_runs", "translations", server_default=None)
    op.alter_column("derivative_runs", "result_count", server_default=None)

    op.add_column(
        "derivative_topics",
        sa.Column("derivative_run_id", sa.Uuid(), nullable=True),
    )
    op.add_column("derivative_topics", sa.Column("title_en", sa.String(length=500), nullable=True))
    op.add_column(
        "derivative_topics",
        sa.Column("description_en", sa.String(length=2000), nullable=True),
    )
    op.add_column(
        "derivative_topics",
        sa.Column("ai_rationale_en", sa.String(length=2000), nullable=True),
    )
    op.add_column("derivative_topics", sa.Column("angle_en", sa.String(length=100), nullable=True))
    op.create_foreign_key(
        "fk_derivative_topics_run",
        "derivative_topics",
        "derivative_runs",
        ["derivative_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_derivative_topic_run", "derivative_topics", ["derivative_run_id"])

    op.add_column("search_queries", sa.Column("query_text_en", sa.String(length=2000), nullable=True))
    op.add_column("search_queries", sa.Column("source_language", sa.String(length=20), nullable=True))
    op.add_column(
        "search_analyses",
        sa.Column(
            "process_log",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "search_analyses",
        sa.Column(
            "translations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("search_analyses", "process_log", server_default=None)
    op.alter_column("search_analyses", "translations", server_default=None)


def downgrade() -> None:
    op.drop_column("search_analyses", "translations")
    op.drop_column("search_analyses", "process_log")
    op.drop_column("search_queries", "source_language")
    op.drop_column("search_queries", "query_text_en")
    op.drop_index("ix_derivative_topic_run", table_name="derivative_topics")
    op.drop_constraint("fk_derivative_topics_run", "derivative_topics", type_="foreignkey")
    op.drop_column("derivative_topics", "angle_en")
    op.drop_column("derivative_topics", "ai_rationale_en")
    op.drop_column("derivative_topics", "description_en")
    op.drop_column("derivative_topics", "title_en")
    op.drop_column("derivative_topics", "derivative_run_id")
    op.drop_index("ix_derivative_run_topic", table_name="derivative_runs")
    op.drop_index("ix_derivative_run_workspace_created", table_name="derivative_runs")
    op.drop_table("derivative_runs")
