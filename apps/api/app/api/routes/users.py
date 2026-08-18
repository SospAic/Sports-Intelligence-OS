from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.auth import (
    CurrentUserResponse,
    UserSummary,
    WorkspaceAccountGrantCreate,
    WorkspaceAccountGrantRead,
    WorkspaceInvitationAccept,
    WorkspaceInvitationCreate,
    WorkspaceInvitationCreateResponse,
    WorkspaceInvitationRead,
    WorkspaceMemberRead,
    WorkspaceMembershipSummary,
    WorkspaceMemberUpdate,
    WorkspaceRole,
)
from app.services.workspace_access import WorkspaceAccessError, WorkspaceAccessService

router = APIRouter(tags=["users"])


def _access_error(exc: WorkspaceAccessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "detail": str(exc)})


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


@router.get("/workspace-invitations", response_model=list[WorkspaceInvitationRead])
async def workspace_invitations(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[WorkspaceInvitationRead]:
    require_workspace_role(workspace, {"owner", "admin"})
    return await WorkspaceAccessService(db).list_invitations(workspace.workspace_id)


@router.post(
    "/workspace-invitations",
    response_model=WorkspaceInvitationCreateResponse,
    status_code=201,
)
async def create_workspace_invitation(
    payload: WorkspaceInvitationCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> WorkspaceInvitationCreateResponse:
    require_workspace_role(workspace, {"owner", "admin"})
    try:
        return await WorkspaceAccessService(db).create_invitation(
            workspace.workspace_id, auth.user.id, payload
        )
    except WorkspaceAccessError as exc:
        raise _access_error(exc) from exc


@router.post("/workspace-invitations/accept", response_model=WorkspaceMemberRead)
async def accept_workspace_invitation(
    payload: WorkspaceInvitationAccept,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> WorkspaceMemberRead:
    try:
        return await WorkspaceAccessService(db).accept_invitation(auth.user.id, payload)
    except WorkspaceAccessError as exc:
        raise _access_error(exc) from exc


@router.post("/workspace-invitations/{invitation_id}/revoke", status_code=204)
async def revoke_workspace_invitation(
    invitation_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> None:
    require_workspace_role(workspace, {"owner", "admin"})
    try:
        await WorkspaceAccessService(db).revoke_invitation(
            workspace.workspace_id, invitation_id, auth.user.id
        )
    except WorkspaceAccessError as exc:
        raise _access_error(exc) from exc


@router.patch("/workspace-members/{member_id}", response_model=WorkspaceMemberRead)
async def update_workspace_member(
    member_id: UUID,
    payload: WorkspaceMemberUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> WorkspaceMemberRead:
    require_workspace_role(workspace, {"owner", "admin"})
    try:
        return await WorkspaceAccessService(db).update_member(
            workspace.workspace_id, member_id, auth.user.id, payload
        )
    except WorkspaceAccessError as exc:
        raise _access_error(exc) from exc


@router.get("/workspace-account-grants", response_model=list[WorkspaceAccountGrantRead])
async def workspace_account_grants(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    account_id: UUID | None = None,
) -> list[WorkspaceAccountGrantRead]:
    require_workspace_role(workspace, {"owner", "admin"})
    return await WorkspaceAccessService(db).list_account_grants(
        workspace.workspace_id, account_id
    )


@router.post(
    "/workspace-account-grants",
    response_model=WorkspaceAccountGrantRead,
    status_code=201,
)
async def create_workspace_account_grant(
    payload: WorkspaceAccountGrantCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> WorkspaceAccountGrantRead:
    require_workspace_role(workspace, {"owner", "admin"})
    try:
        return await WorkspaceAccessService(db).create_account_grant(
            workspace.workspace_id, auth.user.id, payload
        )
    except WorkspaceAccessError as exc:
        raise _access_error(exc) from exc


@router.delete("/workspace-account-grants/{grant_id}", status_code=204)
async def revoke_workspace_account_grant(
    grant_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> None:
    require_workspace_role(workspace, {"owner", "admin"})
    try:
        await WorkspaceAccessService(db).revoke_account_grant(
            workspace.workspace_id, grant_id, auth.user.id
        )
    except WorkspaceAccessError as exc:
        raise _access_error(exc) from exc
