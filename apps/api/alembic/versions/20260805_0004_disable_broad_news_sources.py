"""Disable broad technology feeds that pollute the default sports dashboard.

The expanded-source seed initially enabled a general Data Science feed and the
Hacker News front page.  They remain available as explicit opt-in sources, but
must not contribute articles or topic events to an existing workspace after an
upgrade.  The migration is intentionally limited to the two exact seeded
names; user-created sources are untouched.

Revision ID: 20260805_0004
Revises: 20260805_0003
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0004"
down_revision: str | None = "20260805_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_NAME_MAP = {
    "dev.to · Data Science（开源社区，默认启用）": ("dev.to · Data Science（开源社区，默认停用）"),
    "Hacker News · Front Page（开源社区，默认启用）": (
        "Hacker News · Front Page（开源社区，默认停用）"
    ),
}


def upgrade() -> None:
    for legacy_name, current_name in _LEGACY_NAME_MAP.items():
        # First disable the legacy row even if a previous seed already created
        # the corrected name. This avoids silently leaving the old feed live.
        op.execute(
            sa.text("UPDATE news_sources SET enabled = FALSE WHERE name = :legacy_name").bindparams(
                legacy_name=legacy_name
            )
        )
        # Rename only when the corrected deterministic row does not already
        # exist; the workspace/name unique constraint must remain valid.
        op.execute(
            sa.text(
                "UPDATE news_sources AS legacy SET name = :current_name "
                "WHERE legacy.name = :legacy_name "
                "AND NOT EXISTS ("
                "SELECT 1 FROM news_sources AS current "
                "WHERE current.workspace_id = legacy.workspace_id "
                "AND current.name = :current_name"
                ")"
            ).bindparams(legacy_name=legacy_name, current_name=current_name)
        )
        op.execute(
            sa.text(
                "UPDATE news_sources SET enabled = FALSE WHERE name = :current_name"
            ).bindparams(current_name=current_name)
        )


def downgrade() -> None:
    # Do not re-enable these feeds on downgrade.  They are still valid
    # user-selectable sources, and reverting the migration must not resurrect
    # unrelated articles in a sports workspace.
    pass
