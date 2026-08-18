from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.dependencies import (
    AccountScope,
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.models.monitoring import ContentItem
from app.schemas.publication import (
    AttributionRefreshResponse,
    PublicationCreate,
    PublicationDetail,
    PublicationPage,
    PublicationUpdate,
)
from app.services.publication import PublicationError, PublicationService
from app.services.workspace_access import WorkspaceAccessError, require_account_access

router = APIRouter(prefix="/publications", tags=["publications"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def _raise(exc: PublicationError | WorkspaceAccessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "detail": str(exc)})


@router.get("", response_model=PublicationPage)
async def list_publications(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    scope: AccountScope,
    page: Page = 1,
    page_size: PageSize = 20,
    status: Literal["planned", "scheduled", "published", "unverified", "failed", "cancelled"]
    | None = None,
    content_item_id: UUID | None = None,
) -> PublicationPage:
    return await PublicationService(db).list_publications(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        status=status,
        content_item_id=content_item_id,
        account_ids=scope,
    )


@router.post("", response_model=PublicationDetail, status_code=201)
async def create_publication(
    payload: PublicationCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PublicationDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        account_id = payload.account_id
        if payload.content_item_id is not None:
            account_id = await db.scalar(
                select(ContentItem.account_id).where(
                    ContentItem.workspace_id == workspace.workspace_id,
                    ContentItem.id == payload.content_item_id,
                )
            )
        if account_id is not None:
            await require_account_access(
                db,
                workspace.workspace_id,
                auth.user.id,
                workspace.role,
                account_id,
                require_editor=True,
            )
        return await PublicationService(db).create(workspace.workspace_id, auth.user.id, payload)
    except (PublicationError, WorkspaceAccessError) as exc:
        raise _raise(exc) from exc


@router.get("/{publication_id}", response_model=PublicationDetail)
async def get_publication(
    publication_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> PublicationDetail:
    try:
        detail = await PublicationService(db).get_detail(workspace.workspace_id, publication_id)
        if detail.account_id is not None:
            await require_account_access(
                db,
                workspace.workspace_id,
                workspace.auth.user.id,
                workspace.role,
                detail.account_id,
            )
        return detail
    except (PublicationError, WorkspaceAccessError) as exc:
        raise _raise(exc) from exc


@router.patch("/{publication_id}", response_model=PublicationDetail)
async def update_publication(
    publication_id: UUID,
    payload: PublicationUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PublicationDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    try:
        current = await PublicationService(db).get_detail(workspace.workspace_id, publication_id)
        target_account = (
            payload.account_id if payload.account_id is not None else current.account_id
        )
        if target_account is not None:
            await require_account_access(
                db,
                workspace.workspace_id,
                auth.user.id,
                workspace.role,
                target_account,
                require_editor=True,
            )
        return await PublicationService(db).update(
            workspace.workspace_id, publication_id, auth.user.id, payload
        )
    except (PublicationError, WorkspaceAccessError) as exc:
        raise _raise(exc) from exc


@router.post("/{publication_id}/attribution/refresh", response_model=AttributionRefreshResponse)
async def refresh_publication_attribution(
    publication_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AttributionRefreshResponse:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        current = await PublicationService(db).get_detail(workspace.workspace_id, publication_id)
        if current.account_id is not None:
            await require_account_access(
                db,
                workspace.workspace_id,
                auth.user.id,
                workspace.role,
                current.account_id,
                require_editor=True,
            )
        return await PublicationService(db).refresh_attribution(
            workspace.workspace_id, publication_id, auth.user.id
        )
    except (PublicationError, WorkspaceAccessError) as exc:
        raise _raise(exc) from exc
