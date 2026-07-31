"""Normalize unverified legacy trends and remove redundant indexes.

Revision ID: 20260729_0014
Revises: 20260729_0013
Create Date: 2026-07-29 15:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260729_0014"
down_revision = "20260729_0013"
branch_labels = None
depends_on = None

LEGACY_PROVIDER_KEYS = ("douyin_public_api", "bilibili_public_api")
REDUNDANT_INDEXES = {
    "trend_topics": (
        ("ix_tt_obs", ("observed_at",)),
        ("ix_tt_plat", ("platform",)),
        ("ix_tt_wp", ("workspace_id", "platform")),
    ),
    "trend_videos": (
        ("ix_tv_bo", ("breakout_score",)),
        ("ix_tv_eid", ("external_id",)),
        ("ix_tv_obs", ("observed_at",)),
        ("ix_tv_plat", ("platform",)),
        ("ix_tv_wp", ("workspace_id", "platform")),
    ),
    "trend_keyword_snapshots": (
        ("ix_kw_kw", ("keyword",)),
        ("ix_kw_plat", ("platform",)),
        ("ix_kw_wp", ("workspace_id", "platform")),
        ("ix_trend_kw_keyword", ("keyword",)),
    ),
}


def _existing_indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table, indexes in REDUNDANT_INDEXES.items():
        existing = _existing_indexes(table)
        for name, _columns in indexes:
            if name in existing:
                op.drop_index(name, table_name=table)

    for table in ("trend_topics", "trend_videos", "trend_keyword_snapshots"):
        bind.execute(
            sa.text(
                f"UPDATE {table} SET metadata = metadata || jsonb_build_object("
                "'source_kind', 'imported', "
                "'provider', 'legacy_unverified', "
                "'legacy_provider', metadata->>'provider', "
                "'acceptance_excluded', true) "
                "WHERE metadata->>'provider' IN :providers"
            ).bindparams(sa.bindparam("providers", expanding=True)),
            {"providers": LEGACY_PROVIDER_KEYS},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("trend_topics", "trend_videos", "trend_keyword_snapshots"):
        bind.execute(
            sa.text(
                f"UPDATE {table} SET metadata = "
                "(metadata - 'acceptance_excluded' - 'legacy_provider') || "
                "jsonb_build_object('source_kind', 'live', "
                "'provider', metadata->>'legacy_provider') "
                "WHERE metadata->>'provider' = 'legacy_unverified' "
                "AND metadata->>'legacy_provider' IN :providers"
            ).bindparams(sa.bindparam("providers", expanding=True)),
            {"providers": LEGACY_PROVIDER_KEYS},
        )

    for table, indexes in REDUNDANT_INDEXES.items():
        existing = _existing_indexes(table)
        for name, columns in indexes:
            if name not in existing:
                op.create_index(name, table, list(columns))
