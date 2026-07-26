from typing import cast

from fastapi import APIRouter

from app.api.dependencies import CurrentAuth
from app.schemas.auth import (
    CurrentUserResponse,
    UserSummary,
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
