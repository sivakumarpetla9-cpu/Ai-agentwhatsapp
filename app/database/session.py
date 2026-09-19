from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import get_settings
from app.core.exceptions import DatabaseConnectionError
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Engine creation with connection pooling configured for PostgreSQL
engine_kwargs = {
    "echo": False,
}

if "sqlite" in settings.DATABASE_URL:
    # SQLite configuration (e.g. for testing)
    pass
else:
    # PostgreSQL pooling parameters
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
    })

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an asynchronous SQLAlchemy database session.
    Automatically handles rollback on error and closes the session.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connectivity() -> bool:
    """
    Verifies that the database is reachable by executing a simple SELECT 1 query.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error(f"Database connectivity check failed: {exc}")
        raise DatabaseConnectionError(
            message="Could not establish connection to the database.",
            details={"error": str(exc)}
        ) from exc
