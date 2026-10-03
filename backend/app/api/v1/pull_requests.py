"""Pull Request listing and detail read endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.dashboard import PullRequestRead, ReviewRunRead
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/pull-requests", tags=["Pull Requests"])
dashboard_service = DashboardService()


@router.get(
    "",
    response_model=list[PullRequestRead],
    summary="List Pull Requests",
    description="Returns ingested pull requests with optional filtering.",
)
async def list_pull_requests(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    repository_id: Annotated[
        uuid.UUID | None, Query(description="Filter by repository UUID")
    ] = None,
    state: Annotated[
        str | None, Query(description="Filter by PR state (open/closed)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PullRequestRead]:
    """List pull requests across repositories or filtered by repository."""
    return await dashboard_service.list_pull_requests(
        session, repository_id=repository_id, state=state, limit=limit, offset=offset
    )


@router.get(
    "/{pull_request_id}",
    response_model=PullRequestRead,
    summary="Get Pull Request",
    description="Returns single pull request details by UUID.",
)
async def get_pull_request(
    pull_request_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PullRequestRead:
    """Get single pull request by ID."""
    pr = await dashboard_service.get_pull_request(session, pull_request_id)
    if pr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PullRequest {pull_request_id} not found",
        )
    return pr


@router.get(
    "/{pull_request_id}/reviews",
    response_model=list[ReviewRunRead],
    summary="List PR Review Runs",
    description="Returns all review run executions triggered for a pull request.",
)
async def list_pr_review_runs(
    pull_request_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[
        str | None, Query(alias="status", description="Filter by status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReviewRunRead]:
    """List review runs for a specific PR."""
    pr = await dashboard_service.get_pull_request(session, pull_request_id)
    if pr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PullRequest {pull_request_id} not found",
        )
    return await dashboard_service.list_review_runs(
        session,
        pull_request_id=pull_request_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
