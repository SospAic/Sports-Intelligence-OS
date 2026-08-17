"""Add explicit saved-search metadata to smart search history."""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0008"
down_revision = "20260817_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_queries",
        sa.Column("saved_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "search_queries",
        sa.Column("is_saved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_search_queries_is_saved", "search_queries", ["is_saved"])
    op.alter_column("search_queries", "is_saved", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_search_queries_is_saved", table_name="search_queries")
    op.drop_column("search_queries", "is_saved")
    op.drop_column("search_queries", "saved_name")
