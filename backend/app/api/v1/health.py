"""Health check and dependency readiness API endpoints.

Provides liveness and readiness probe routes. Utilizes existing database
and Redis connectivity checkers with dependency injection to ensure full
modularity and testability.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.core.redis import check_redis_connection
from app.database.session import check_db_connection
from app.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


async def check_database_dependency() -> DependencyStatus:
    """Check connectivity to PostgreSQL persistence engine."""
    start = time.perf_counter()
    try:
        is_healthy = await check_db_connection()
        latency = (time.perf_counter() - start) * 1000.0
        if is_healthy:
            return DependencyStatus(
                status="healthy",
                latency_ms=round(latency, 2),
                details="connected",
            )
        return DependencyStatus(
            status="unhealthy",
            latency_ms=round(latency, 2),
            details="database ping returned false",
        )
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000.0
        logger.warning("Database readiness check failed: %s", exc)
        return DependencyStatus(
            status="unhealthy",
            latency_ms=round(latency, 2),
            details="connection failed",
        )


async def check_redis_dependency() -> DependencyStatus:
    """Check connectivity to Redis cache and task broker."""
    start = time.perf_counter()
    try:
        is_healthy = await check_redis_connection()
        latency = (time.perf_counter() - start) * 1000.0
        if is_healthy:
            return DependencyStatus(
                status="healthy",
                latency_ms=round(latency, 2),
                details="connected",
            )
        return DependencyStatus(
            status="unhealthy",
            latency_ms=round(latency, 2),
            details="redis ping returned false",
        )
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000.0
        logger.warning("Redis readiness check failed: %s", exc)
        return DependencyStatus(
            status="unhealthy",
            latency_ms=round(latency, 2),
            details="connection failed",
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Liveness Probe",
    description="Returns the liveness status, application name, version, and environment.",
)
async def get_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Liveness probe indicating that the FastAPI application is alive."""
    return HealthResponse(
        status="ok",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "All infrastructure dependencies are healthy."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "One or more infrastructure dependencies are unhealthy."
        },
    },
    summary="Application Readiness Probe",
    description="Verifies connectivity to PostgreSQL and Redis without leaking credentials.",
)
async def get_readiness(
    response: Response,
    db_status: Annotated[DependencyStatus, Depends(check_database_dependency)],
    redis_status: Annotated[DependencyStatus, Depends(check_redis_dependency)],
) -> ReadinessResponse:
    """Readiness probe validating persistence and queue connectivity."""
    is_ready = db_status.status == "healthy" and redis_status.status == "healthy"

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        readiness_status = "degraded"
    else:
        response.status_code = status.HTTP_200_OK
        readiness_status = "ready"

    return ReadinessResponse(
        status=readiness_status,
        database=db_status,
        redis=redis_status,
    )
