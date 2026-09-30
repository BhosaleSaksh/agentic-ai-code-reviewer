from collections.abc import AsyncGenerator

import pytest
from app.database.session import async_engine, check_db_connection, get_db_session
from sqlalchemy import text


@pytest.fixture(autouse=True)
async def cleanup_database_engine() -> AsyncGenerator[None, None]:
    """Dispose engine connections between isolated test event loops."""
    yield
    await async_engine.dispose()


@pytest.mark.integration
async def test_database_healthcheck() -> None:
    """Verify asynchronous database connection ping succeeds."""
    connected = await check_db_connection()
    assert connected is True


@pytest.mark.integration
async def test_database_session_select_one() -> None:
    """Verify executing a basic query through get_db_session."""
    async for session in get_db_session():
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.integration
async def test_database_is_postgresql_16() -> None:
    """Verify connected PostgreSQL instance is version 16 (from Docker).

    Ensures the application communicates with the containerized PostgreSQL 16
    service on port 5433 rather than the host native PostgreSQL 18 instance.
    """
    async for session in get_db_session():
        result = await session.execute(text("SELECT version();"))
        version_str = str(result.scalar())
        assert "PostgreSQL 16" in version_str
