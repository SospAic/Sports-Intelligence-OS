import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(status="ok", service="api", version=settings.app_version)


@router.get("/health/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    settings = request.app.state.settings
    checks: dict[str, Literal["ok", "error"]] = {
        "database": "error",
        "redis": "error",
    }

    try:
        async with request.app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning(
            "readiness_database_failed",
            extra={"event": "health.database.failed", "error_type": type(exc).__name__},
        )

    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning(
            "readiness_redis_failed",
            extra={"event": "health.redis.failed", "error_type": type(exc).__name__},
        )

    if all(value == "ok" for value in checks.values()):
        return HealthResponse(
            status="ok", service="api", version=settings.app_version, checks=checks
        )
    return JSONResponse(
        status_code=503,
        content=HealthResponse(
            status="degraded", service="api", version=settings.app_version, checks=checks
        ).model_dump(),
    )
