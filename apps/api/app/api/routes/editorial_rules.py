import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.schemas.editorial_rules import (
    RuleBatchUpdate,
    RuleDiffRead,
    RuleEditResult,
    RuleImportRequest,
    RuleImportResult,
    RulePage,
    RuleSetCreate,
    RuleSetDetail,
    RuleSetPage,
    RuleSetRead,
    RuleSetVersionRead,
    RuleTreeRead,
    RuleUpdate,
    ValidationResultRead,
    VersionActionRequest,
    VersionCreate,
)
from app.services.editorial_rules import EditorialRuleError, EditorialRuleService

router = APIRouter(prefix="/rules", tags=["editorial-rules"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


async def editorial_rule_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, EditorialRuleError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="规则中心请求失败",
        detail=str(exc),
    )


def service(db: DatabaseSession) -> EditorialRuleService:
    return EditorialRuleService(db)


@router.get("", response_model=RuleSetPage)
async def list_rule_sets(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    query: str | None = None,
    status: Literal["active", "disabled", "archived"] | None = None,
) -> RuleSetPage:
    return await service(db).list_rule_sets(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        query=query,
        status=status,
    )


@router.post("", response_model=RuleSetRead, status_code=201)
async def create_rule_set(
    payload: RuleSetCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> RuleSetRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).create_rule_set(workspace.workspace_id, auth.user.id, payload)


@router.post("/import", response_model=RuleImportResult, status_code=201)
async def import_rules(
    payload: RuleImportRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> RuleImportResult:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).import_request(workspace.workspace_id, auth.user.id, payload)


@router.get("/{rule_set_id}", response_model=RuleSetDetail)
async def get_rule_set(
    rule_set_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> RuleSetDetail:
    return await service(db).rule_set_detail(workspace.workspace_id, rule_set_id)


@router.post("/{rule_set_id}/versions", response_model=RuleSetVersionRead, status_code=201)
async def create_version(
    rule_set_id: UUID,
    payload: VersionCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> RuleSetVersionRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).create_draft(
        workspace.workspace_id, rule_set_id, auth.user.id, payload
    )


@router.get("/{rule_set_id}/versions/{version_id}", response_model=RuleSetVersionRead)
async def get_version(
    rule_set_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> RuleSetVersionRead:
    return await service(db).get_version(workspace.workspace_id, rule_set_id, version_id)


@router.get("/{rule_set_id}/versions/{version_id}/tree", response_model=RuleTreeRead)
async def get_tree(
    rule_set_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> RuleTreeRead:
    return await service(db).get_tree(workspace.workspace_id, rule_set_id, version_id)


@router.get("/{rule_set_id}/versions/{version_id}/sections")
async def list_sections_lazy(
    rule_set_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    parent_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 50,
) -> dict[str, Any]:
    """Return sections at one level with children counts for lazy tree loading."""
    from sqlalchemy import func, select

    from app.models.editorial_rules import Rule, RuleSection

    # Validate the complete ownership chain before any raw section query. A
    # version UUID from another workspace must never disclose tree metadata.
    await service(db).get_version(workspace.workspace_id, rule_set_id, version_id)

    base_filter = [
        RuleSection.version_id == version_id,
    ]
    if parent_id is not None:
        base_filter.append(RuleSection.parent_id == parent_id)
    else:
        base_filter.append(RuleSection.parent_id.is_(None))

    total = int(
        await db.scalar(select(func.count()).select_from(RuleSection).where(*base_filter)) or 0
    )
    sections = (
        await db.scalars(
            select(RuleSection)
            .where(*base_filter)
            .order_by(RuleSection.sort_order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    # Compute children count and rules count for each section
    items = []
    for section in sections:
        children_count = int(
            await db.scalar(
                select(func.count())
                .select_from(RuleSection)
                .where(RuleSection.parent_id == section.id)
            )
            or 0
        )
        rules_count = int(
            await db.scalar(
                select(func.count())
                .select_from(Rule)
                .where(Rule.section_id == section.id)
            )
            or 0
        )
        items.append({
            "id": str(section.id),
            "title": section.title,
            "slug": section.slug,
            "parent_id": str(section.parent_id) if section.parent_id else None,
            "sort_order": section.sort_order,
            "children_count": children_count,
            "rules_count": rules_count,
            "has_children": children_count > 0,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{rule_set_id}/versions/{version_id}/rules", response_model=RulePage)
async def list_rules(
    rule_set_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
    query: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
    rule_type: str | None = None,
    is_mandatory: bool | None = None,
    enabled: bool | None = None,
) -> RulePage:
    return await service(db).list_rules(
        workspace.workspace_id,
        rule_set_id,
        version_id,
        page=page,
        page_size=page_size,
        query=query,
        tags=tags or [],
        rule_type=rule_type,
        is_mandatory=is_mandatory,
        enabled=enabled,
    )


@router.patch("/{rule_set_id}/versions/{version_id}/rules/{rule_id}", response_model=RuleEditResult)
async def update_rule(
    rule_set_id: UUID,
    version_id: UUID,
    rule_id: UUID,
    payload: RuleUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> RuleEditResult:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).update_rule(
        workspace.workspace_id,
        rule_set_id,
        version_id,
        rule_id,
        auth.user.id,
        payload,
    )


@router.patch("/{rule_set_id}/versions/{version_id}/rules")
async def batch_update_rules(
    rule_set_id: UUID,
    version_id: UUID,
    payload: RuleBatchUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> dict[str, object]:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    effective_version_id, created_draft, updated = await service(db).batch_update(
        workspace.workspace_id,
        rule_set_id,
        version_id,
        auth.user.id,
        payload,
    )
    return {"version_id": effective_version_id, "created_draft": created_draft, "updated": updated}


@router.post("/{rule_set_id}/versions/{version_id}/validate", response_model=ValidationResultRead)
async def validate_version(
    rule_set_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ValidationResultRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await service(db).validate_version(workspace.workspace_id, rule_set_id, version_id)


@router.post("/{rule_set_id}/versions/{version_id}/publish", response_model=RuleSetVersionRead)
async def publish_version(
    rule_set_id: UUID,
    version_id: UUID,
    payload: VersionActionRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> RuleSetVersionRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(db).publish(
        workspace.workspace_id, rule_set_id, version_id, auth.user.id, payload.reason
    )


@router.post("/{rule_set_id}/versions/{version_id}/rollback", response_model=RuleSetVersionRead)
async def rollback_version(
    rule_set_id: UUID,
    version_id: UUID,
    payload: VersionActionRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> RuleSetVersionRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(db).rollback(
        workspace.workspace_id, rule_set_id, version_id, auth.user.id, payload.reason
    )


@router.get("/{rule_set_id}/compare", response_model=RuleDiffRead)
async def compare_versions(
    rule_set_id: UUID,
    left: UUID,
    right: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> RuleDiffRead:
    return await service(db).compare(workspace.workspace_id, rule_set_id, left, right)


@router.get("/{rule_set_id}/versions/{version_id}/export")
async def export_version(
    rule_set_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    format: Literal["txt", "json"] = "json",
) -> Response:
    rules = service(db)
    if format == "txt":
        content = await rules.source_text(workspace.workspace_id, rule_set_id, version_id)
        return PlainTextResponse(
            content,
            headers={"Content-Disposition": f'attachment; filename="rules-{version_id}.txt"'},
        )
    content = await rules.export_json(workspace.workspace_id, rule_set_id, version_id)
    return JSONResponse(
        content=json.loads(content),
        headers={"Content-Disposition": f'attachment; filename="rules-{version_id}.json"'},
    )
