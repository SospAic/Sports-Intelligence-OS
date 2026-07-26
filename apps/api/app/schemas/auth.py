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


class CurrentUserResponse(BaseModel):
    user: UserSummary
    memberships: list[WorkspaceMembershipSummary]
