"""Dashboard metrics and overview read endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.dashboard import DashboardMetrics
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
dashboard_service = DashboardService()


@router.get(
    "/metrics",
    response_model=DashboardMetrics,
    summary="Get Dashboard Metrics",
    description="Returns high-level aggregate metrics for the code review platform.",
)
async def get_dashboard_metrics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DashboardMetrics:
    """Retrieve aggregate framework metrics for observability."""
    return await dashboard_service.get_metrics(session)
