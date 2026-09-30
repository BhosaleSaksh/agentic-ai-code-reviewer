"""Comprehensive test suite for FastAPI application foundation and health routes.

Covers application factory configuration, root and versioned health/readiness
endpoints, dependency injection failure modes, credential non-disclosure,
CORS policies, and error handling.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.api.v1.health import (
    check_database_dependency,
    check_redis_dependency,
)
from app.core.config import Settings, get_settings
from app.database.session import async_engine
from app.main import app, create_app, lifespan
from app.schemas.health import (
    DependencyStatus,
    HealthResponse,
    ReadinessResponse,
)


@pytest.fixture(autouse=True)
async def cleanup_database_engine() -> AsyncGenerator[None, None]:
    """Dispose engine connections between isolated test executions."""
    yield
    await async_engine.dispose()
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an asynchronous HTTP client configured with ASGITransport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.unit
def test_create_app_default_metadata() -> None:
    """Verify application factory creates FastAPI instance with correct defaults."""
    settings = get_settings()
    test_app = create_app()

    assert test_app.title == settings.PROJECT_NAME
    assert test_app.version == settings.VERSION
    assert test_app.docs_url == "/docs"
    assert test_app.redoc_url == "/redoc"
    assert test_app.openapi_url == "/openapi.json"


@pytest.mark.unit
def test_create_app_production_metadata() -> None:
    """Verify application factory disables API docs in production mode."""
    prod_settings = Settings(
        PROJECT_NAME="Production Reviewer",
        VERSION="2.0.0",
        ENVIRONMENT="production",
        DEBUG=False,
    )
    test_app = create_app(custom_settings=prod_settings)

    assert test_app.title == "Production Reviewer"
    assert test_app.version == "2.0.0"
    assert test_app.docs_url is None
    assert test_app.redoc_url is None
    assert test_app.openapi_url is None


@pytest.mark.unit
def test_api_router_registration_and_paths() -> None:
    """Verify expected health and readiness routes exist in the OpenAPI schema."""
    openapi = app.openapi()
    paths = openapi.get("paths", {})

    assert "/health" in paths
    assert "/health/ready" in paths
    assert "/api/v1/health" in paths
    assert "/api/v1/health/ready" in paths


@pytest.mark.unit
async def test_root_health_liveness(async_client: httpx.AsyncClient) -> None:
    """Verify GET /health returns 200 with valid HealthResponse schema."""
    response = await async_client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    validated = HealthResponse.model_validate(payload)
    assert validated.status == "ok"
    assert validated.service == "Agentic AI Code Reviewer"
    assert validated.version == "0.1.0"
    assert validated.environment == "development"


@pytest.mark.unit
async def test_api_v1_health_liveness(async_client: httpx.AsyncClient) -> None:
    """Verify GET /api/v1/health returns 200 matching architectural specification."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.json()
    validated = HealthResponse.model_validate(payload)
    assert validated.status == "ok"
    assert validated.service == "Agentic AI Code Reviewer"
    assert validated.version == "0.1.0"


@pytest.mark.integration
async def test_api_v1_readiness_all_dependencies_healthy(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify GET /api/v1/health/ready returns 200 when PostgreSQL and Redis are up."""
    response = await async_client.get("/api/v1/health/ready")
    assert response.status_code == 200

    payload = response.json()
    validated = ReadinessResponse.model_validate(payload)
    assert validated.status == "ready"
    assert validated.database.status == "healthy"
    assert validated.database.details == "connected"
    assert validated.database.latency_ms is not None
    assert validated.database.latency_ms >= 0.0

    assert validated.redis.status == "healthy"
    assert validated.redis.details == "connected"
    assert validated.redis.latency_ms is not None
    assert validated.redis.latency_ms >= 0.0


@pytest.mark.integration
async def test_root_readiness_endpoint(async_client: httpx.AsyncClient) -> None:
    """Verify GET /health/ready root mirror returns 200 when dependencies are healthy."""
    response = await async_client.get("/health/ready")
    assert response.status_code == 200

    payload = response.json()
    validated = ReadinessResponse.model_validate(payload)
    assert validated.status == "ready"
    assert validated.database.status == "healthy"
    assert validated.redis.status == "healthy"


@pytest.mark.unit
async def test_readiness_when_database_unhealthy(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify GET /api/v1/health/ready returns 503 degraded when database check fails."""
    app.dependency_overrides[check_database_dependency] = lambda: DependencyStatus(
        status="unhealthy",
        latency_ms=25.5,
        details="connection failed",
    )

    response = await async_client.get("/api/v1/health/ready")
    assert response.status_code == 503

    payload = response.json()
    validated = ReadinessResponse.model_validate(payload)
    assert validated.status == "degraded"
    assert validated.database.status == "unhealthy"
    assert validated.database.details == "connection failed"
    assert validated.redis.status == "healthy"


@pytest.mark.unit
async def test_readiness_when_redis_unhealthy(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify GET /api/v1/health/ready returns 503 degraded when Redis check fails."""
    app.dependency_overrides[check_redis_dependency] = lambda: DependencyStatus(
        status="unhealthy",
        latency_ms=10.2,
        details="connection failed",
    )

    response = await async_client.get("/api/v1/health/ready")
    assert response.status_code == 503

    payload = response.json()
    validated = ReadinessResponse.model_validate(payload)
    assert validated.status == "degraded"
    assert validated.database.status == "healthy"
    assert validated.redis.status == "unhealthy"
    assert validated.redis.details == "connection failed"


@pytest.mark.unit
async def test_readiness_when_both_dependencies_unhealthy(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify GET /api/v1/health/ready returns 503 when both DB and Redis fail."""
    app.dependency_overrides[check_database_dependency] = lambda: DependencyStatus(
        status="unhealthy",
        latency_ms=50.0,
        details="connection failed",
    )
    app.dependency_overrides[check_redis_dependency] = lambda: DependencyStatus(
        status="unhealthy",
        latency_ms=45.0,
        details="connection failed",
    )

    response = await async_client.get("/api/v1/health/ready")
    assert response.status_code == 503

    payload = response.json()
    validated = ReadinessResponse.model_validate(payload)
    assert validated.status == "degraded"
    assert validated.database.status == "unhealthy"
    assert validated.redis.status == "unhealthy"


@pytest.mark.unit
async def test_check_database_dependency_exception_handling() -> None:
    """Verify check_database_dependency catches exceptions and marks unhealthy."""
    with patch(
        "app.api.v1.health.check_db_connection",
        new=AsyncMock(side_effect=ConnectionRefusedError("Simulated DB offline")),
    ):
        result = await check_database_dependency()
        assert result.status == "unhealthy"
        assert result.details == "connection failed"
        assert result.latency_ms is not None


@pytest.mark.unit
async def test_check_database_dependency_returns_false() -> None:
    """Verify check_database_dependency handles false return value."""
    with patch(
        "app.api.v1.health.check_db_connection",
        new=AsyncMock(return_value=False),
    ):
        result = await check_database_dependency()
        assert result.status == "unhealthy"
        assert result.details == "database ping returned false"


@pytest.mark.unit
async def test_check_redis_dependency_exception_handling() -> None:
    """Verify check_redis_dependency catches exceptions and marks unhealthy."""
    with patch(
        "app.api.v1.health.check_redis_connection",
        new=AsyncMock(side_effect=TimeoutError("Simulated Redis timeout")),
    ):
        result = await check_redis_dependency()
        assert result.status == "unhealthy"
        assert result.details == "connection failed"
        assert result.latency_ms is not None


@pytest.mark.unit
async def test_check_redis_dependency_returns_false() -> None:
    """Verify check_redis_dependency handles false return value."""
    with patch(
        "app.api.v1.health.check_redis_connection",
        new=AsyncMock(return_value=False),
    ):
        result = await check_redis_dependency()
        assert result.status == "unhealthy"
        assert result.details == "redis ping returned false"


@pytest.mark.unit
async def test_security_no_credentials_in_health_responses(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify neither passwords, tokens, nor connection strings leak in API responses."""
    settings = get_settings()
    sensitive_tokens = [
        settings.POSTGRES_PASSWORD.get_secret_value(),
        settings.SECRET_KEY.get_secret_value(),
        "postgresql+asyncpg://",
        "redis://",
        "password",
        "secret",
    ]

    for path in ["/health", "/health/ready", "/api/v1/health", "/api/v1/health/ready"]:
        response = await async_client.get(path)
        raw_body = response.text.lower()
        for token in sensitive_tokens:
            assert token.lower() not in raw_body, f"Token '{token}' leaked in {path}"


@pytest.mark.unit
async def test_cors_middleware_headers(async_client: httpx.AsyncClient) -> None:
    """Verify CORS headers are returned for allowed origins."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    response = await async_client.options("/health", headers=headers)
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


@pytest.mark.unit
async def test_nonexistent_route_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """Verify request to unknown path returns standard 404 response."""
    response = await async_client.get("/api/v1/nonexistent")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.unit
async def test_lifespan_lifecycle() -> None:
    """Verify application lifespan initializes and disposes cleanly."""
    test_app = create_app()
    with patch(
        "sqlalchemy.ext.asyncio.AsyncEngine.dispose",
        new_callable=AsyncMock,
    ) as mock_dispose:
        async with lifespan(test_app):
            # Application is active inside context
            assert mock_dispose.call_count == 0
        # Engine dispose must be called on lifespan exit
        assert mock_dispose.call_count == 1
