"""Infrastructure tests for asynchronous Redis connectivity."""

import pytest
from app.core.config import get_settings
from app.core.redis import check_redis_connection, get_redis_client, get_redis_session


@pytest.mark.integration
async def test_redis_healthcheck() -> None:
    """Verify asynchronous Redis PING healthcheck succeeds."""
    connected = await check_redis_connection()
    assert connected is True


@pytest.mark.integration
async def test_redis_client_ping() -> None:
    """Verify direct async client ping command execution."""
    client = get_redis_client()
    try:
        response = await client.ping()
        assert response is True
    finally:
        aclose_func = getattr(client, "aclose", None)
        if callable(aclose_func):
            await aclose_func()
        else:
            await client.close()


@pytest.mark.integration
async def test_redis_session_generator() -> None:
    """Verify clean context management with get_redis_session."""
    async for client in get_redis_session():
        response = await client.ping()
        assert response is True


@pytest.mark.integration
def test_redis_port_is_6380() -> None:
    """Verify configured development host port matches Phase 1.1 resolution."""
    settings = get_settings()
    assert settings.REDIS_PORT == 6380
