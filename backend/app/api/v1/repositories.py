"""Repository listing and detail read endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.dashboard import PullRequestRead, RepositoryRead
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/repositories", tags=["Repositories"])
dashboard_service = DashboardService()


@router.get(
    "",
    response_model=list[RepositoryRead],
    summary="List Repositories",
    description="Returns all registered GitHub repositories with PR counts.",
)
async def list_repositories(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[
        int, Query(ge=1, le=500, description="Max records to return")
    ] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset pagination")] = 0,
) -> list[RepositoryRead]:
    """List monitored repositories."""
    return await dashboard_service.list_repositories(
        session, limit=limit, offset=offset
    )


@router.get(
    "/{repository_id}",
    response_model=RepositoryRead,
    summary="Get Repository",
    description="Returns details for a single repository by UUID.",
)
async def get_repository(
    repository_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RepositoryRead:
    """Get single repository by ID."""
    repo = await dashboard_service.get_repository(session, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found",
        )
    return repo


@router.get(
    "/{repository_id}/pull-requests",
    response_model=list[PullRequestRead],
    summary="List Repository Pull Requests",
    description="Returns pull requests associated with a repository.",
)
async def list_repository_pull_requests(
    repository_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    state: Annotated[
        str | None, Query(description="Filter by PR state (open/closed)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PullRequestRead]:
    """List pull requests for a specific repository."""
    # Verify repo exists first
    repo = await dashboard_service.get_repository(session, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found",
        )
    return await dashboard_service.list_pull_requests(
        session, repository_id=repository_id, state=state, limit=limit, offset=offset
    )
