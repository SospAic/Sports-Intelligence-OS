from fastapi import APIRouter

from app.api.routes import (
    auth,
    automation,
    editorial_rules,
    generation,
    monitoring,
    news,
    operations,
    topics,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(monitoring.router)
api_router.include_router(news.router)
api_router.include_router(editorial_rules.router)
api_router.include_router(generation.router)
api_router.include_router(automation.router)
api_router.include_router(topics.router)
api_router.include_router(operations.router)
