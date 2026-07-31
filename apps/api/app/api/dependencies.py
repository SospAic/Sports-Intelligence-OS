from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.security import hash_secret, secure_compare_hash
from app.models.session import AuthSession
from app.models.user import User
from app.models.workspace import WorkspaceMembership


@dataclass(frozen=True)
class AuthContext:
    session: AuthSession
    user: User


WorkspaceRole = Literal["owner", "admin", "editor", "analyst", "viewer"]


@dataclass(frozen=True)
class WorkspaceContext:
    auth: AuthContext
    workspace_id: UUID
    role: WorkspaceRole


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_auth(
    request: Request,
    db: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="sio_session")] = None,
) -> AuthContext:
    settings = request.app.state.settings
    cookie_name = settings.session_cookie_name
    if cookie_name != "sio_session":
        session_token = request.cookies.get(cookie_name)
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "detail": "请先登录"},
        )

    statement = (
        select(AuthSession)
        .options(
            joinedload(AuthSession.user)
            .selectinload(User.memberships)
            .joinedload(WorkspaceMembership.workspace)
        )
        .where(
            AuthSession.token_hash == hash_secret(session_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    result = await db.execute(statement)
    auth_session = result.unique().scalar_one_or_none()
    if auth_session is None or auth_session.user.status != "active":
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_session", "detail": "会话无效或已过期"},
        )
    return AuthContext(session=auth_session, user=auth_session.user)


CurrentAuth = Annotated[AuthContext, Depends(get_current_auth)]


async def get_current_workspace(
    auth: CurrentAuth,
    workspace_header: Annotated[UUID | None, Header(alias="X-Workspace-Id")] = None,
) -> WorkspaceContext:
    memberships = [
        membership
        for membership in auth.user.memberships
        if membership.status == "active" and membership.workspace.status == "active"
    ]
    if workspace_header is not None:
        membership = next(
            (item for item in memberships if item.workspace_id == workspace_header), None
        )
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "detail": "无权访问该工作区"},
            )
    elif len(memberships) == 1:
        membership = memberships[0]
    elif not memberships:
        raise HTTPException(
            status_code=403,
            detail={"code": "workspace_required", "detail": "当前用户没有可用工作区"},
        )
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "workspace_header_required",
                "detail": "用户属于多个工作区，请提供 X-Workspace-Id",
            },
        )
    return WorkspaceContext(
        auth=auth,
        workspace_id=membership.workspace_id,
        role=membership.role,  # type: ignore[arg-type]
    )


CurrentWorkspace = Annotated[WorkspaceContext, Depends(get_current_workspace)]


def require_workspace_role(
    workspace: WorkspaceContext, allowed: set[WorkspaceRole]
) -> WorkspaceContext:
    if workspace.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": "permission_denied", "detail": "当前角色无权执行此操作"},
        )
    return workspace


async def require_csrf(
    auth: CurrentAuth,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if not csrf_token or not secure_compare_hash(csrf_token, auth.session.csrf_token_hash):
        raise HTTPException(
            status_code=403,
            detail={"code": "csrf_validation_failed", "detail": "CSRF 校验失败"},
        )
    return auth


CsrfProtectedAuth = Annotated[AuthContext, Depends(require_csrf)]
