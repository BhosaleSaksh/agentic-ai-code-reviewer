"""Reviewer feedback read endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.enums import FeedbackType
from app.schemas.publication import FeedbackFilter, FeedbackResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/feedback", tags=["Feedback"])
dashboard_service = DashboardService()


@router.get(
    "",
    response_model=list[FeedbackResponse],
    summary="List Feedback Events",
    description="Returns persisted developer feedback, reactions, and resolution events.",
)
async def list_feedback(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    repository_id: Annotated[
        int | None, Query(description="GitHub repository numeric ID")
    ] = None,
    pr_number: Annotated[int | None, Query(description="PR number")] = None,
    finding_id: Annotated[uuid.UUID | None, Query(description="Finding UUID")] = None,
    review_run_id: Annotated[
        uuid.UUID | None, Query(description="Review run UUID")
    ] = None,
    feedback_type: Annotated[
        FeedbackType | None, Query(description="Feedback type enum")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FeedbackResponse]:
    """List feedback with optional query filters."""
    filter_params = FeedbackFilter(
        repository_id=repository_id,
        pr_number=pr_number,
        finding_id=finding_id,
        review_run_id=review_run_id,
        feedback_type=feedback_type,
    )
    return await dashboard_service.list_feedback(
        session, filter_params=filter_params, limit=limit, offset=offset
    )


@router.get(
    "/{feedback_id}",
    response_model=FeedbackResponse,
    summary="Get Feedback Event",
    description="Returns single feedback record by UUID.",
)
async def get_feedback(
    feedback_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackResponse:
    """Get single feedback event by ID."""
    fb = await dashboard_service.get_feedback_by_id(session, feedback_id)
    if fb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feedback {feedback_id} not found",
        )
    return fb
