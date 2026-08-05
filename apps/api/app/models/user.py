from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.session import AuthSession
    from app.models.workspace import WorkspaceMembership


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="user_status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    email_display: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
