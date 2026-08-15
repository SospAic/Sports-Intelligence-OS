from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
)
from app.models.view_preference import UserViewPreference
from app.schemas.view_preference import ViewPreferenceRead, ViewPreferenceUpdate

router = APIRouter(prefix="/accounts/view-preferences", tags=["monitoring"])


@router.get("", response_model=ViewPreferenceRead | None)
async def get_view_preferences(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    view: Literal["accounts", "contents"] = Query("accounts"),
) -> ViewPreferenceRead | None:
    """Return the current user's account-list view preferences for this workspace."""
    result = await db.execute(
        select(UserViewPreference).where(
            UserViewPreference.workspace_id == workspace.workspace_id,
            UserViewPreference.user_id == workspace.auth.user.id,
            UserViewPreference.view_key == view,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return ViewPreferenceRead.model_validate(row)


@router.put("", response_model=ViewPreferenceRead)
async def update_view_preferences(
    payload: ViewPreferenceUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    view: Literal["accounts", "contents"] = Query("accounts"),
) -> ViewPreferenceRead:
    """Create or update the current user's account-list view preferences."""
    result = await db.execute(
        select(UserViewPreference).where(
            UserViewPreference.workspace_id == workspace.workspace_id,
            UserViewPreference.user_id == auth.user.id,
            UserViewPreference.view_key == view,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserViewPreference(
            workspace_id=workspace.workspace_id,
            user_id=auth.user.id,
            view_key=view,
            preferences=payload.preferences,
        )
        db.add(row)
    else:
        row.preferences = payload.preferences
    await db.flush()
    await db.refresh(row)
    return ViewPreferenceRead.model_validate(row)
