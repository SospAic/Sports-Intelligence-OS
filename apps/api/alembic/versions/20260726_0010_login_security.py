"""Add hashed login attempts for distributed rate limiting.

Revision ID: 20260726_0010
Revises: 20260726_0009
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_attempted_at", "login_attempts", ["attempted_at"])
    op.create_index(
        "ix_login_attempts_identity_time", "login_attempts", ["identity_hash", "attempted_at"]
    )
    op.create_index("ix_login_attempts_ip_time", "login_attempts", ["ip_hash", "attempted_at"])


def downgrade() -> None:
    op.drop_table("login_attempts")
