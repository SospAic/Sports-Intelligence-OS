from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

import app.services.sync as sync_module
from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.repositories.monitoring import AccountFilters, ContentFilters
from app.schemas.monitoring import (
    AccountCreate,
    AccountPage,
    AccountRead,
    AccountSnapshotPage,
    AccountSort,
    AccountUpdate,
    ContentPage,
    ContentRead,
    ContentSnapshotPage,
    ContentSort,
    DerivedMetricPage,
    PlatformRead,
    SortOrder,
    SyncRunPage,
    SyncRunRead,
)
from app.services.monitoring import MonitoringError, MonitoringService
from app.services.sync import SyncDispatchError, SyncError, SyncService

router = APIRouter(tags=["monitoring"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


async def monitoring_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, MonitoringError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="监控数据请求失败",
        detail=str(exc),
    )


async def sync_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, SyncError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="平台同步请求失败",
        detail=str(exc),
    )


@router.get("/platforms", response_model=list[PlatformRead])
async def list_platforms(
    _: CurrentAuth,
    db: DatabaseSession,
    enabled: bool | None = None,
) -> list[PlatformRead]:
    return await MonitoringService(db).list_platforms(enabled=enabled)


@router.post("/accounts", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).create_account(workspace.workspace_id, auth.user.id, payload)


@router.get("/accounts/export.csv")
async def export_accounts(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: AccountSort = "created_at",
    order: SortOrder = "desc",
    platform: str | None = None,
    query: str | None = None,
    is_active: bool | None = None,
) -> Response:
    csv_text = await MonitoringService(db).export_accounts_csv(
        workspace.workspace_id,
        AccountFilters(platform=platform, query=query, is_active=is_active),
        sort,
        order,
    )
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="accounts.csv"'},
    )


@router.get("/accounts", response_model=AccountPage)
async def list_accounts(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: AccountSort = "created_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    platform: str | None = None,
    query: str | None = None,
    is_active: bool | None = None,
) -> AccountPage:
    return await MonitoringService(db).list_accounts(
        workspace.workspace_id,
        filters=AccountFilters(platform=platform, query=query, is_active=is_active),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/accounts/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> AccountRead:
    return await MonitoringService(db).get_account(workspace.workspace_id, account_id)


@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).update_account(
        workspace.workspace_id, account_id, auth.user.id, payload
    )


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> None:
    require_workspace_role(workspace, {"owner", "admin"})
    await MonitoringService(db).disable_account(workspace.workspace_id, account_id, auth.user.id)


@router.post("/accounts/{account_id}/sync", response_model=SyncRunRead, status_code=202)
async def request_account_sync(
    account_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SyncRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = SyncService(
        db,
        request.app.state.platform_adapters,
        request.app.state.settings,
    )
    run, created = await service.request_account_sync(
        workspace.workspace_id,
        account_id,
        request_id=str(request.state.request_id),
    )
    if created:
        try:
            sync_module.enqueue_platform_sync(run.id)
        except Exception as exc:
            await service.mark_dispatch_failure(run.id)
            raise SyncDispatchError("background task broker is unavailable") from exc
    return run


@router.get("/accounts/{account_id}/sync-runs", response_model=SyncRunPage)
async def list_account_sync_runs(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> SyncRunPage:
    return await SyncService(
        db,
        request.app.state.platform_adapters,
        request.app.state.settings,
    ).list_account_runs(
        workspace.workspace_id,
        account_id,
        page=page,
        page_size=page_size,
    )


@router.get("/accounts/{account_id}/snapshots", response_model=AccountSnapshotPage)
async def list_account_snapshots(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
) -> AccountSnapshotPage:
    return await MonitoringService(db).account_snapshots(
        workspace.workspace_id, account_id, page=page, page_size=page_size
    )


@router.get("/accounts/{account_id}/contents", response_model=ContentPage)
async def list_account_contents(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: ContentSort = "published_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    platform: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_views: Annotated[int | None, Query(ge=0)] = None,
    max_views: Annotated[int | None, Query(ge=0)] = None,
    query: str | None = None,
) -> ContentPage:
    service = MonitoringService(db)
    await service.get_account(workspace.workspace_id, account_id)
    return await service.list_contents(
        workspace.workspace_id,
        filters=ContentFilters(
            platform=platform,
            account=account_id,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            query=query,
        ),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/contents/export.csv")
async def export_contents(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: ContentSort = "published_at",
    order: SortOrder = "desc",
    platform: str | None = None,
    account: UUID | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_views: Annotated[int | None, Query(ge=0)] = None,
    max_views: Annotated[int | None, Query(ge=0)] = None,
    query: str | None = None,
) -> Response:
    csv_text = await MonitoringService(db).export_contents_csv(
        workspace.workspace_id,
        ContentFilters(
            platform=platform,
            account=account,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            query=query,
        ),
        sort,
        order,
    )
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contents.csv"'},
    )


@router.get("/contents", response_model=ContentPage)
async def list_contents(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: ContentSort = "published_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    platform: str | None = None,
    account: UUID | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_views: Annotated[int | None, Query(ge=0)] = None,
    max_views: Annotated[int | None, Query(ge=0)] = None,
    query: str | None = None,
) -> ContentPage:
    return await MonitoringService(db).list_contents(
        workspace.workspace_id,
        filters=ContentFilters(
            platform=platform,
            account=account,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            query=query,
        ),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/contents/{content_id}", response_model=ContentRead)
async def get_content(
    content_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> ContentRead:
    return await MonitoringService(db).get_content(workspace.workspace_id, content_id)


@router.get("/contents/{content_id}/snapshots", response_model=ContentSnapshotPage)
async def list_content_snapshots(
    content_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
) -> ContentSnapshotPage:
    return await MonitoringService(db).content_snapshots(
        workspace.workspace_id, content_id, page=page, page_size=page_size
    )


@router.get("/contents/{content_id}/metrics", response_model=DerivedMetricPage)
async def list_content_metrics(
    content_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
) -> DerivedMetricPage:
    return await MonitoringService(db).content_metrics(
        workspace.workspace_id, content_id, page=page, page_size=page_size
    )
