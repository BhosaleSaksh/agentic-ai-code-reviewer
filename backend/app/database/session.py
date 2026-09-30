"""Asynchronous SQLAlchemy database engine and session management.

Provides modern SQLAlchemy 2.x async engine, async session factory,
and session generator dependency. Obtains configuration exclusively
from app.core.config.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

# Create the global async SQLAlchemy engine
async_engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    echo=settings.DEBUG and settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# Async session factory bound to the engine
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated asynchronous database session.

    Commits on successful block execution, rolls back on exception,
    and reliably closes the session.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db_connection() -> bool:
    """Verify database connectivity with a lightweight ping query."""
    async with async_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        scalar = result.scalar()
        return bool(scalar == 1)
