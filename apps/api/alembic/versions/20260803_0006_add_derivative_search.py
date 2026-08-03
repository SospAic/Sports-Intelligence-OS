"""Add derivative topics + smart search analysis tables.

Powers the "热点情报中心" (Hotspot Intelligence Center) module:
``derivative_topics`` (existing + AI-predicted derivative angles per trend
topic) and ``search_queries`` / ``search_analyses`` (natural-language search
and its LLM analysis).

Revision ID: 20260803_0006
Revises: 20260803_0005
Create Date: 2026-08-03 17:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260803_0006"
down_revision = "20260803_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "derivative_topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_topic_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("angle", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("predicted_heat_score", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("ai_rationale", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("adopted_generation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_derivative_topic_workspace", "derivative_topics", ["workspace_id"])
    op.create_index("ix_derivative_topic_source", "derivative_topics", ["source_topic_id"])
    op.create_index("ix_derivative_topic_kind", "derivative_topics", ["workspace_id", "kind"])

    op.create_table(
        "search_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("query_text", sa.String(length=2000), nullable=False),
        sa.Column("platform_scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_query_workspace", "search_queries", ["workspace_id"])

    op.create_table(
        "search_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("search_query_id", sa.Uuid(), nullable=False),
        sa.Column("related_hotness", sa.Float(), nullable=True),
        sa.Column("volume_estimate", sa.JSON(), nullable=True),
        sa.Column("sentiment", sa.String(length=50), nullable=True),
        sa.Column("timeline_phases", sa.JSON(), nullable=True),
        sa.Column("platform_distribution", sa.JSON(), nullable=True),
        sa.Column("related_derivative_topics", sa.JSON(), nullable=True),
        sa.Column("summary", sa.String(length=4000), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("raw_llm", sa.JSON(), nullable=True),
        sa.Column("results_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["search_query_id"], ["search_queries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_analysis_workspace", "search_analyses", ["workspace_id"])
    op.create_index("ix_search_analysis_query", "search_analyses", ["search_query_id"])


def downgrade() -> None:
    op.drop_table("search_analyses")
    op.drop_table("search_queries")
    op.drop_table("derivative_topics")
