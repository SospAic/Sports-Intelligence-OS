"""Allow multiple historical invitations while keeping one pending invite."""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0012"
down_revision = "20260817_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_workspace_invitation_status", "workspace_invitations", type_="unique"
    )
    op.create_index(
        "uq_workspace_invitations_pending_email",
        "workspace_invitations",
        ["workspace_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_invitations_pending_email", table_name="workspace_invitations")
    op.create_unique_constraint(
        "uq_workspace_invitation_status",
        "workspace_invitations",
        ["workspace_id", "email_normalized", "status"],
    )
