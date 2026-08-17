"""Add optional per-member account access grants."""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0013"
down_revision = "20260817_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_account_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
            "permission IN ('viewer', 'editor')", name="account_grant_permission"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "account_id",
            "user_id",
            name="uq_workspace_account_grant_member_account",
        ),
    )
    op.create_index(
        "ix_workspace_account_grants_workspace_id",
        "workspace_account_grants",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_account_grants_account_id",
        "workspace_account_grants",
        ["account_id"],
    )
    op.create_index(
        "ix_workspace_account_grants_user_id",
        "workspace_account_grants",
        ["user_id"],
    )
    op.create_index(
        "ix_workspace_account_grants_member",
        "workspace_account_grants",
        ["workspace_id", "user_id"],
    )
    op.create_index(
        "ix_workspace_account_grants_account",
        "workspace_account_grants",
        ["workspace_id", "account_id"],
    )


def downgrade() -> None:
    op.drop_table("workspace_account_grants")
