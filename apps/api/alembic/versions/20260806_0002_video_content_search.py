"""Add scheduled video-content search plans, runs, candidates and evidence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260806_0002"
down_revision: str | None = "20260806_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "video_search_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("query_text", sa.String(2000), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_candidates", sa.Integer(), nullable=False),
        sa.Column("min_match_score", sa.Float(), nullable=False),
        sa.Column("content_mode", sa.String(32), nullable=False),
        sa.Column("analyzer_key", sa.String(80), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'error')", name="video_search_plan_status"
        ),
        sa.CheckConstraint(
            "interval_seconds >= 60 AND interval_seconds <= 2592000",
            name="video_search_plan_interval",
        ),
        sa.CheckConstraint(
            "max_candidates >= 1 AND max_candidates <= 200", name="video_search_plan_max_candidates"
        ),
        sa.CheckConstraint(
            "min_match_score >= 0 AND min_match_score <= 1", name="video_search_plan_score_range"
        ),
    )
    op.create_index("ix_video_search_plans_workspace_id", "video_search_plans", ["workspace_id"])
    op.create_index("ix_video_search_plans_status", "video_search_plans", ["status"])
    op.create_index(
        "ix_video_search_plans_workspace_status", "video_search_plans", ["workspace_id", "status"]
    )
    op.create_index("ix_video_search_plans_due", "video_search_plans", ["status", "next_run_at"])

    op.create_table(
        "video_search_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("analyzed_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["plan_id"], ["video_search_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            (
                "status IN ('queued', 'running', 'stopping', 'completed', "
                "'partial', 'failed', 'stopped')"
            ),
            name="video_search_run_status",
        ),
    )
    op.create_index("ix_video_search_runs_plan_id", "video_search_runs", ["plan_id"])
    op.create_index("ix_video_search_runs_workspace_id", "video_search_runs", ["workspace_id"])
    op.create_index("ix_video_search_runs_status", "video_search_runs", ["status"])
    op.create_index(
        "ix_video_search_runs_workspace_created",
        "video_search_runs",
        ["workspace_id", "created_at"],
    )
    op.create_index("ix_video_search_runs_plan_status", "video_search_runs", ["plan_id", "status"])

    op.create_table(
        "video_search_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("last_run_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("canonical_url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=True),
        sa.Column("author_name", sa.String(255), nullable=True),
        sa.Column("cover_url", sa.String(2000), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_match_status", sa.String(20), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("analysis_provider", sa.String(80), nullable=True),
        sa.Column("analysis_model", sa.String(120), nullable=True),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_provider", sa.String(80), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["plan_id"], ["video_search_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_run_id"], ["video_search_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "canonical_url", name="uq_video_search_candidate_plan_url"),
        sa.CheckConstraint(
            (
                "content_match_status IN ('discovered', 'analyzing', 'matched', "
                "'rejected', 'unavailable', 'failed')"
            ),
            name="video_search_candidate_status",
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="video_search_candidate_score_range",
        ),
    )
    op.create_index("ix_video_search_candidates_plan_id", "video_search_candidates", ["plan_id"])
    op.create_index(
        "ix_video_search_candidates_last_run_id", "video_search_candidates", ["last_run_id"]
    )
    op.create_index(
        "ix_video_search_candidates_workspace_id", "video_search_candidates", ["workspace_id"]
    )
    op.create_index("ix_video_search_candidates_platform", "video_search_candidates", ["platform"])
    op.create_index(
        "ix_video_search_candidates_external_id", "video_search_candidates", ["external_id"]
    )
    op.create_index(
        "ix_video_search_candidates_content_match_status",
        "video_search_candidates",
        ["content_match_status"],
    )
    op.create_index(
        "ix_video_search_candidates_workspace_status",
        "video_search_candidates",
        ["workspace_id", "content_match_status"],
    )
    op.create_index(
        "ix_video_search_candidates_plan_score",
        "video_search_candidates",
        ["plan_id", "content_match_status", "match_score"],
    )


def downgrade() -> None:
    op.drop_table("video_search_candidates")
    op.drop_table("video_search_runs")
    op.drop_table("video_search_plans")
