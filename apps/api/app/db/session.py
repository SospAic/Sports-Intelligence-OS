from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine_and_session(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    # Sports Intelligence OS supports PostgreSQL exclusively. The pool and
    # per-command timeout options are PostgreSQL-specific and always applied.
    engine_options: dict[str, object] = {
        "pool_pre_ping": True,
        "echo": False,
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout_seconds,
        "pool_recycle": settings.database_pool_recycle_seconds,
        "connect_args": {"command_timeout": settings.database_command_timeout_seconds},
    }
    engine = create_async_engine(settings.database_url, **engine_options)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory
