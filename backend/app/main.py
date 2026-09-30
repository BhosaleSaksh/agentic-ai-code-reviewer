"""FastAPI application factory and main entry point.

Provides a composable create_app factory with lifecycle management,
CORS middleware, and versioned API routing.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.v1.health import (
    check_database_dependency,
    check_redis_dependency,
    get_readiness,
)
from app.core.config import Settings, get_settings
from app.core.redis import close_arq_redis_pool
from app.database.session import async_engine
from app.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle events."""
    # Startup actions (if any required in future)
    yield
    # Shutdown actions: cleanly dispose ARQ Redis pool and database engine pool
    await close_arq_redis_pool()
    await async_engine.dispose()


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    """Create and configure a FastAPI application instance."""
    app_settings = custom_settings or get_settings()

    app = FastAPI(
        title=app_settings.PROJECT_NAME,
        version=app_settings.VERSION,
        description=(
            "An Agentic AI Framework for Reliable and Evidence-Based "
            "Automated Code Review"
        ),
        lifespan=lifespan,
        docs_url="/docs" if app_settings.DEBUG else None,
        redoc_url="/redoc" if app_settings.DEBUG else None,
        openapi_url="/openapi.json" if app_settings.DEBUG else None,
    )

    # Configure CORS middleware
    if app_settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Register root liveness probe for container orchestrators (e.g. Docker/Kubernetes)
    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health"],
        summary="Root Liveness Probe",
        description="Returns basic application liveness metadata.",
    )
    async def root_health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=app_settings.PROJECT_NAME,
            version=app_settings.VERSION,
            environment=app_settings.ENVIRONMENT,
        )

    # Register root readiness probe for container orchestrators
    @app.get(
        "/health/ready",
        response_model=ReadinessResponse,
        tags=["Health"],
        summary="Root Readiness Probe",
        description="Verifies connectivity to PostgreSQL and Redis without leaking credentials.",
        responses={
            status.HTTP_200_OK: {
                "description": "All infrastructure dependencies are healthy."
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": "One or more infrastructure dependencies are unhealthy."
            },
        },
    )
    async def root_readiness(
        response: Response,
        db_status: Annotated[DependencyStatus, Depends(check_database_dependency)],
        redis_status: Annotated[DependencyStatus, Depends(check_redis_dependency)],
    ) -> ReadinessResponse:
        return await get_readiness(
            response=response,
            db_status=db_status,
            redis_status=redis_status,
        )

    # Include versioned API routers
    app.include_router(api_router)

    return app


# Default module-level application instance for ASGI servers (e.g., uvicorn app.main:app)
app: FastAPI = create_app()
