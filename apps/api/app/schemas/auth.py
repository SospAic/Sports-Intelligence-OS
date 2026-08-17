from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    locale: str
    timezone: str


class AuthResponse(BaseModel):
    user: UserSummary
    csrf_token: str
    expires_at: datetime


class CsrfResponse(BaseModel):
    csrf_token: str


WorkspaceRole = Literal["owner", "admin", "editor", "analyst", "viewer"]


class WorkspaceMembershipSummary(BaseModel):
    workspace_id: UUID
    workspace_name: str
    role: WorkspaceRole


class WorkspaceMemberRead(BaseModel):
    id: UUID
    display_name: str
    email: str
    role: WorkspaceRole


class WorkspaceMemberUpdate(BaseModel):
    role: Literal["admin", "editor", "analyst", "viewer"] | None = None
    status: Literal["active", "disabled"] | None = None


class WorkspaceInvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "editor", "analyst", "viewer"] = "viewer"
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class WorkspaceInvitationRead(BaseModel):
    id: UUID
    workspace_id: UUID
    email: EmailStr
    role: Literal["admin", "editor", "analyst", "viewer"]
    status: Literal["pending", "accepted", "revoked", "expired"]
    invited_by: UUID
    accepted_by: UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkspaceInvitationCreateResponse(WorkspaceInvitationRead):
    token: str


class WorkspaceInvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class WorkspaceAccountGrantCreate(BaseModel):
    account_id: UUID
    user_id: UUID
    permission: Literal["viewer", "editor"] = "viewer"


class WorkspaceAccountGrantRead(BaseModel):
    id: UUID
    workspace_id: UUID
    account_id: UUID
    user_id: UUID
    permission: Literal["viewer", "editor"]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class CurrentUserResponse(BaseModel):
    user: UserSummary
    memberships: list[WorkspaceMembershipSummary]
