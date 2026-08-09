import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

logger = logging.getLogger(__name__)


async def _install_vector_codec(raw_connection: Any) -> None:
    await raw_connection.set_type_codec(
        "vector",
        schema="public",
        encoder=str,
        decoder=str,
        format="text",
    )


def _register_pgvector_codec(engine: AsyncEngine) -> None:
    """Teach asyncpg how to talk to pgvector's ``vector`` type.

    asyncpg refuses to bind a parameter whose PostgreSQL type it does not
    recognise, so without a codec every insert into a ``vector`` column fails.
    We register a pass-through **text** codec: ``app.models.embedding.Vector``
    already converts between Python sequences and pgvector's ``[1,2,3]``
    textual form, so asyncpg only has to move the string across the wire.

    The extension may legitimately be absent (fresh database, or a deployment
    that never enabled semantic search). In that case the lookup raises and we
    degrade quietly — everything else must keep working.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        try:
            dbapi_connection.run_async(_install_vector_codec)
        except Exception:  # noqa: BLE001 - pgvector is an optional extension
            logger.debug("pgvector codec not registered; semantic search unavailable")


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
    _register_pgvector_codec(engine)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory
