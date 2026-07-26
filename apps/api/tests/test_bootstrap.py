from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.security import verify_password
from app.db.base import Base
from app.models.operations import AuditEntry
from app.models.workspace import WorkspaceMembership
from app.services.bootstrap import bootstrap_admin

ADMIN_PASSWORD = "bootstrap-test-password"  # noqa: S105 - test fixture only


@pytest.mark.asyncio
async def test_bootstrap_creates_owner_and_audit_entry(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    settings = Settings(environment="test", password_min_length=12)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            user = await bootstrap_admin(
                session,
                settings,
                email="Admin@Example.com",
                password=ADMIN_PASSWORD,
                display_name="管理员",
                workspace_name="测试工作区",
            )
            assert user.email_normalized == "admin@example.com"
            assert verify_password(ADMIN_PASSWORD, user.password_hash)

        async with session_factory() as session:
            owner_count = await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.role == "owner")
            )
            audit_count = await session.scalar(select(func.count()).select_from(AuditEntry))
            assert owner_count == 1
            assert audit_count == 1
            with pytest.raises(ValueError, match="already exists"):
                await bootstrap_admin(
                    session,
                    settings,
                    email="admin@example.com",
                    password=ADMIN_PASSWORD,
                    display_name="另一个管理员",
                    workspace_name="测试工作区",
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_rejects_invalid_email_before_writing(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'invalid.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    settings = Settings(environment="test")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            with pytest.raises(ValueError, match="administrator email must be valid"):
                await bootstrap_admin(
                    session,
                    settings,
                    email="not-an-email",
                    password=ADMIN_PASSWORD,
                    display_name="管理员",
                    workspace_name="测试工作区",
                )
    finally:
        await engine.dispose()
