"""Per-account access grants for workspace members."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkspaceAccountGrant(TimestampMixin, Base):
    """An optional explicit read/write scope for a non-admin workspace member.

    Members without grants retain the workspace role's legacy full-workspace
    access. Once a member has at least one grant, account reads and writes are
    limited to the granted accounts; owners/admins always bypass this layer.
    """

    __tablename__ = "workspace_account_grants"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "account_id",
            "user_id",
            name="uq_workspace_account_grant_member_account",
        ),
        CheckConstraint("permission IN ('viewer', 'editor')", name="account_grant_permission"),
        Index("ix_workspace_account_grants_member", "workspace_id", "user_id"),
        Index("ix_workspace_account_grants_account", "workspace_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
