from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "type": f"https://sports-intelligence.local/problems/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if errors:
        payload["errors"] = errors
    return JSONResponse(
        status_code=status,
        content=payload,
        media_type="application/problem+json",
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    detail = str(exc.detail)
    code = "http_error"
    if isinstance(exc.detail, dict):
        detail = str(exc.detail.get("detail", "请求失败"))
        code = str(exc.detail.get("code", code))
    return problem_response(
        request,
        status=exc.status_code,
        code=code,
        title="请求失败",
        detail=detail,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [
        {
            "path": ".".join(str(part) for part in error["loc"]),
            "code": str(error["type"]),
            "message": str(error["msg"]),
        }
        for error in exc.errors()
    ]
    return problem_response(
        request,
        status=422,
        code="validation_error",
        title="请求参数无效",
        detail="一个或多个字段无效",
        errors=errors,
    )
