from typing import cast

from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import CurrentAuth, CurrentWorkspace, DatabaseSession
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.auth import (
    CurrentUserResponse,
    UserSummary,
    WorkspaceMemberRead,
    WorkspaceMembershipSummary,
    WorkspaceRole,
)

router = APIRouter(tags=["users"])


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(auth: CurrentAuth) -> CurrentUserResponse:
    memberships = [
        WorkspaceMembershipSummary(
            workspace_id=membership.workspace_id,
            workspace_name=membership.workspace.name,
            role=cast(WorkspaceRole, membership.role),
        )
        for membership in auth.user.memberships
        if membership.status == "active" and membership.workspace.status == "active"
    ]
    return CurrentUserResponse(
        user=UserSummary(
            id=auth.user.id,
            email=auth.user.email_display,
            display_name=auth.user.display_name,
            locale=auth.user.locale,
            timezone=auth.user.timezone,
        ),
        memberships=memberships,
    )


@router.get("/workspace-members", response_model=list[WorkspaceMemberRead])
async def workspace_members(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[WorkspaceMemberRead]:
    rows = await db.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace.workspace_id,
            WorkspaceMembership.status == "active",
            User.status == "active",
        )
        .order_by(User.display_name.asc(), User.email_display.asc())
    )
    return [
        WorkspaceMemberRead(
            id=user.id,
            display_name=user.display_name or user.email_display,
            email=user.email_display,
            role=membership.role,
        )
        for membership, user in rows.all()
    ]
