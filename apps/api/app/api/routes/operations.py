from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentWorkspace, DatabaseSession
from app.schemas.operations import AuditEntryPage, OperationTaskPage, SystemEventPage
from app.services.operations import OperationsService

router = APIRouter(prefix="/operations", tags=["operations"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


@router.get("/tasks", response_model=OperationTaskPage)
async def list_tasks(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    category: str | None = None,
    status: str | None = None,
) -> OperationTaskPage:
    return await OperationsService(db).tasks(
        workspace.workspace_id, page=page, page_size=page_size, category=category, status=status
    )


@router.get("/events", response_model=SystemEventPage)
async def list_events(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    severity: str | None = None,
    category: str | None = None,
) -> SystemEventPage:
    return await OperationsService(db).events(
        workspace.workspace_id, page=page, page_size=page_size, severity=severity, category=category
    )


@router.get("/audits", response_model=AuditEntryPage)
async def list_audits(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    action: str | None = None,
    resource_type: str | None = None,
) -> AuditEntryPage:
    return await OperationsService(db).audits(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        action=action,
        resource_type=resource_type,
    )
