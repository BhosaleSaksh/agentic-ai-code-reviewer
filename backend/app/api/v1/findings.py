"""Finding detail and attached evidence read endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/findings", tags=["Findings"])
dashboard_service = DashboardService()


@router.get(
    "",
    response_model=list[ReviewFinding],
    summary="List Findings",
    description="Returns findings with critic verification status, evidence items, and filters.",
)
async def list_findings(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    review_run_id: Annotated[
        uuid.UUID | None, Query(description="Review run UUID filter")
    ] = None,
    verification_status: Annotated[
        str | None, Query(description="Verification status filter")
    ] = None,
    severity: Annotated[str | None, Query(description="Severity filter")] = None,
    issue_type: Annotated[str | None, Query(description="Issue type filter")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReviewFinding]:
    """List findings with optional query filters."""
    return await dashboard_service.list_findings(
        session,
        review_run_id=review_run_id,
        verification_status=verification_status,
        severity=severity,
        issue_type=issue_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{finding_id}",
    response_model=ReviewFinding,
    summary="Get Finding",
    description="Returns single finding details with critic verification notes and evidence items.",
)
async def get_finding(
    finding_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReviewFinding:
    """Get single finding by ID."""
    finding = await dashboard_service.get_finding(session, finding_id)
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found",
        )
    return finding


@router.get(
    "/{finding_id}/evidence",
    response_model=list[EvidenceModel],
    summary="List Finding Evidence",
    description="Returns all verifiable evidence items grounding a specific finding.",
)
async def list_finding_evidence(
    finding_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[EvidenceModel]:
    """List evidence items for a specific finding."""
    finding = await dashboard_service.get_finding(session, finding_id)
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found",
        )
    return await dashboard_service.list_evidence_for_finding(session, finding_id)
