from fastapi import APIRouter, Request, Response

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.schemas.settings import (
    LLMProviderSettingRead,
    LLMProviderSettingUpdate,
    LLMProviderTestRead,
    RuntimeSettingsRead,
)
from app.services.settings import SettingsError, SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


async def settings_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, SettingsError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="设置请求失败",
        detail=str(exc),
    )


def service(request: Request, db: DatabaseSession) -> SettingsService:
    return SettingsService(
        db,
        request.app.state.settings,
        request.app.state.llm_providers,
    )


@router.get("/runtime", response_model=RuntimeSettingsRead)
async def runtime_settings(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> RuntimeSettingsRead:
    del workspace
    return service(request, db).runtime_settings()


@router.get("/llm/openai-compatible", response_model=LLMProviderSettingRead)
async def get_llm_setting(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> LLMProviderSettingRead:
    return await service(request, db).llm_setting(workspace.workspace_id)


@router.put("/llm/openai-compatible", response_model=LLMProviderSettingRead)
async def update_llm_setting(
    payload: LLMProviderSettingUpdate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> LLMProviderSettingRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).update_llm_setting(
        workspace.workspace_id, auth.user.id, payload
    )


@router.post("/llm/openai-compatible/test", response_model=LLMProviderTestRead)
async def test_llm_setting(
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> LLMProviderTestRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).test_llm_setting(workspace.workspace_id, auth.user.id)
