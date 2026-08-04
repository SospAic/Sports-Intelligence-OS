"""Scope content_items unique key by account_id.

Previously the unique constraint was (workspace_id, platform_id,
external_id), which forced every video to belong to exactly one account
within a workspace. When the same video is featured on more than one tracked
account (e.g. ``@olympics`` and ``@olympicsbringsustogether`` both publish the
same Olympic clips), the second account's sync finds the existing row,
``skip_existing`` drops it, and the run reports ``success`` while the account
shows zero videos — a hollow success that looks "permanently broken".

Adding ``account_id`` to the unique key lets each account own its own copy of
a shared video, so re-syncing an account populates its 作品 tab correctly.

Revision ID: 20260804_0001
Revises: 20260803_0006
Create Date: 2026-08-04 15:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260804_0001"
down_revision = "20260803_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_content_items_workspace_id", "content_items", type_="unique")
    op.create_unique_constraint(
        "uq_content_items_account",
        "content_items",
        ["workspace_id", "platform_id", "account_id", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_content_items_account", "content_items", type_="unique")
    op.create_unique_constraint(
        "uq_content_items_workspace_id",
        "content_items",
        ["workspace_id", "platform_id", "external_id"],
    )
