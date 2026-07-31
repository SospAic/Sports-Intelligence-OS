import re
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_password, normalize_email
from app.models.operations import AuditEntry
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

EMAIL_ADAPTER = TypeAdapter(EmailStr)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:80] or "sports-intelligence-os"


async def bootstrap_admin(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    display_name: str,
    workspace_name: str,
) -> User:
    if len(password) < settings.password_min_length:
        raise ValueError(
            f"administrator password must be at least {settings.password_min_length} characters"
        )

    try:
        validated_email = str(EMAIL_ADAPTER.validate_python(email))
    except ValidationError as exc:
        raise ValueError("administrator email must be valid") from exc

    normalized_email = normalize_email(validated_email)
    existing_user = await session.scalar(
        select(User).where(User.email_normalized == normalized_email)
    )
    if existing_user is not None:
        raise ValueError(
            "a user with this email already exists; bootstrap will not reset passwords"
        )

    workspace_slug = slugify(workspace_name)
    workspace = await session.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    now = datetime.now(UTC)
    if workspace is None:
        workspace = Workspace(
            id=uuid4(),
            name=workspace_name,
            slug=workspace_slug,
            status="active",
            default_timezone="Asia/Shanghai",
            row_version=1,
        )
        session.add(workspace)

    user = User(
        id=uuid4(),
        email_normalized=normalized_email,
        email_display=validated_email,
        password_hash=hash_password(password),
        display_name=display_name.strip(),
        status="active",
        locale="zh-CN",
        timezone="Asia/Shanghai",
    )
    session.add(user)
    await session.flush()

    membership = WorkspaceMembership(
        id=uuid4(),
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        status="active",
        invited_by=None,
        joined_at=now,
    )
    session.add(membership)
    session.add(
        AuditEntry(
            id=uuid4(),
            workspace_id=workspace.id,
            actor_type="system",
            actor_id=None,
            action="identity.bootstrap_admin.created",
            resource_type="user",
            resource_id=user.id,
            before_hash=None,
            after_hash=None,
            change_summary_json={"email": normalized_email, "role": "owner"},
            reason="initial administrator bootstrap",
            ip_hash=None,
            trace_id=uuid4(),
            created_at=now,
        )
    )
    await session.commit()
    return user
