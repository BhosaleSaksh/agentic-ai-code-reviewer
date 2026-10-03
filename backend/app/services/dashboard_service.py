"""Read-only dashboard service providing queries for the review frontend.

Implements query layer for:
- Framework overview and health metrics
- Repository listings and details
- Pull Request progress and review run linkage
- Review Run executions, findings, and evidence grounding
- Verification results and GitHub publication audit trails
- Reviewer feedback history
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models.evidence_item import EvidenceItem
from app.database.models.feedback import ReviewFeedback
from app.database.models.finding import Finding
from app.database.models.publication import ReviewPublication
from app.database.models.pull_request import PullRequest
from app.database.models.repository import Repository
from app.database.models.review_run import ReviewRun
from app.schemas.dashboard import (
    DashboardMetrics,
    PullRequestRead,
    RepositoryRead,
    ReviewRunRead,
)
from app.schemas.enums import (
    FeedbackSource,
    FeedbackType,
    PublishStatus,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.publication import (
    FeedbackFilter,
    FeedbackResponse,
    PublicationResult,
)
from app.services.finding_mapper import orm_to_evidence, orm_to_finding

logger = logging.getLogger(__name__)


class DashboardService:
    """Service providing read-only queries for the Review Dashboard and API endpoints."""

    async def get_metrics(self, session: AsyncSession) -> DashboardMetrics:
        """Compute aggregated review framework observability metrics from database."""
        # Repositories count
        repo_count = (
            await session.execute(select(func.count(Repository.id)))
        ).scalar() or 0

        # Pull Requests count
        pr_count = (
            await session.execute(select(func.count(PullRequest.id)))
        ).scalar() or 0

        # Review Runs count
        rr_count = (
            await session.execute(select(func.count(ReviewRun.id)))
        ).scalar() or 0

        # Active Review Runs (QUEUED or RUNNING)
        active_rr_count = (
            await session.execute(
                select(func.count(ReviewRun.id)).where(
                    ReviewRun.status.in_(["QUEUED", "RUNNING"])
                )
            )
        ).scalar() or 0

        # Total findings
        total_findings = (
            await session.execute(select(func.count(Finding.id)))
        ).scalar() or 0

        # Verified findings
        verified_findings = (
            await session.execute(
                select(func.count(Finding.id)).where(
                    Finding.verification_status == VerificationStatus.VERIFIED.value
                )
            )
        ).scalar() or 0

        # Rejected findings (rejected, suppressed, or dropped)
        rejected_findings = (
            await session.execute(
                select(func.count(Finding.id)).where(
                    Finding.verification_status.in_(
                        [
                            VerificationStatus.REJECTED.value,
                            VerificationStatus.SUPPRESSED_FALSE_POSITIVE.value,
                            VerificationStatus.DROPPED_LOW_CONFIDENCE.value,
                        ]
                    )
                )
            )
        ).scalar() or 0

        # Published comments
        published_findings = (
            await session.execute(
                select(func.count(ReviewPublication.id)).where(
                    ReviewPublication.publication_status
                    == PublishStatus.PUBLISHED.value
                )
            )
        ).scalar() or 0

        # Feedback events
        total_feedback = (
            await session.execute(select(func.count(ReviewFeedback.id)))
        ).scalar() or 0

        return DashboardMetrics(
            total_repositories=repo_count,
            total_pull_requests=pr_count,
            total_review_runs=rr_count,
            active_review_runs=active_rr_count,
            total_findings=total_findings,
            verified_findings=verified_findings,
            rejected_findings=rejected_findings,
            published_findings=published_findings,
            total_feedback_events=total_feedback,
        )

    async def list_repositories(
        self,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RepositoryRead]:
        """Fetch registered repositories with pull request counts."""
        # Query repositories ordered by latest created
        stmt = (
            select(
                Repository,
                func.count(PullRequest.id).label("pr_count"),
            )
            .outerjoin(PullRequest, PullRequest.repository_id == Repository.id)
            .group_by(Repository.id)
            .order_by(desc(Repository.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = result.all()

        return [
            RepositoryRead(
                id=repo.id,
                github_repo_id=repo.github_repo_id,
                full_name=repo.full_name,
                default_branch=repo.default_branch,
                is_active=repo.is_active,
                created_at=repo.created_at,
                updated_at=repo.updated_at,
                pull_requests_count=pr_count,
            )
            for repo, pr_count in rows
        ]

    async def get_repository(
        self,
        session: AsyncSession,
        repository_id: uuid.UUID,
    ) -> RepositoryRead | None:
        """Fetch single repository by UUID."""
        stmt = (
            select(
                Repository,
                func.count(PullRequest.id).label("pr_count"),
            )
            .outerjoin(PullRequest, PullRequest.repository_id == Repository.id)
            .where(Repository.id == repository_id)
            .group_by(Repository.id)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row is None:
            return None

        repo, pr_count = row
        return RepositoryRead(
            id=repo.id,
            github_repo_id=repo.github_repo_id,
            full_name=repo.full_name,
            default_branch=repo.default_branch,
            is_active=repo.is_active,
            created_at=repo.created_at,
            updated_at=repo.updated_at,
            pull_requests_count=pr_count,
        )

    async def list_pull_requests(
        self,
        session: AsyncSession,
        repository_id: uuid.UUID | None = None,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PullRequestRead]:
        """Fetch pull requests with optional filtering and latest review run info."""
        stmt = (
            select(PullRequest)
            .options(
                selectinload(PullRequest.repository),
                selectinload(PullRequest.review_runs),
            )
            .order_by(desc(PullRequest.created_at))
        )
        if repository_id is not None:
            stmt = stmt.where(PullRequest.repository_id == repository_id)
        if state is not None:
            stmt = stmt.where(PullRequest.state == state.lower())

        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        prs = result.scalars().all()

        output: list[PullRequestRead] = []
        for pr in prs:
            # Sort review runs by created_at desc to find latest
            latest_run = None
            if pr.review_runs:
                sorted_runs = sorted(
                    pr.review_runs, key=lambda r: r.created_at, reverse=True
                )
                latest_run = sorted_runs[0]

            output.append(
                PullRequestRead(
                    id=pr.id,
                    repository_id=pr.repository_id,
                    repository_full_name=pr.repository.full_name
                    if pr.repository
                    else None,
                    pr_number=pr.pr_number,
                    title=pr.title,
                    author=pr.author,
                    base_sha=pr.base_sha,
                    head_sha=pr.head_sha,
                    state=pr.state,
                    additions=pr.additions,
                    deletions=pr.deletions,
                    changed_files_count=pr.changed_files_count,
                    created_at=pr.created_at,
                    updated_at=pr.updated_at,
                    review_runs_count=len(pr.review_runs),
                    latest_review_run_id=latest_run.id if latest_run else None,
                    latest_review_run_status=latest_run.status if latest_run else None,
                )
            )
        return output

    async def get_pull_request(
        self,
        session: AsyncSession,
        pull_request_id: uuid.UUID,
    ) -> PullRequestRead | None:
        """Fetch single pull request by UUID with latest review run info."""
        stmt = (
            select(PullRequest)
            .options(
                selectinload(PullRequest.repository),
                selectinload(PullRequest.review_runs),
            )
            .where(PullRequest.id == pull_request_id)
        )
        result = await session.execute(stmt)
        pr = result.scalar_one_or_none()
        if pr is None:
            return None

        latest_run = None
        if pr.review_runs:
            sorted_runs = sorted(
                pr.review_runs, key=lambda r: r.created_at, reverse=True
            )
            latest_run = sorted_runs[0]

        return PullRequestRead(
            id=pr.id,
            repository_id=pr.repository_id,
            repository_full_name=pr.repository.full_name if pr.repository else None,
            pr_number=pr.pr_number,
            title=pr.title,
            author=pr.author,
            base_sha=pr.base_sha,
            head_sha=pr.head_sha,
            state=pr.state,
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files_count=pr.changed_files_count,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            review_runs_count=len(pr.review_runs),
            latest_review_run_id=latest_run.id if latest_run else None,
            latest_review_run_status=latest_run.status if latest_run else None,
        )

    async def list_review_runs(
        self,
        session: AsyncSession,
        pull_request_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewRunRead]:
        """Fetch review runs with findings count and publication status summary."""
        stmt = (
            select(ReviewRun)
            .options(
                selectinload(ReviewRun.pull_request).selectinload(
                    PullRequest.repository
                ),
                selectinload(ReviewRun.findings),
                selectinload(ReviewRun.publications),
            )
            .order_by(desc(ReviewRun.created_at))
        )
        if pull_request_id is not None:
            stmt = stmt.where(ReviewRun.pull_request_id == pull_request_id)
        if status is not None:
            stmt = stmt.where(ReviewRun.status == status.upper())

        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        runs = result.scalars().all()

        output: list[ReviewRunRead] = []
        for run in runs:
            findings = run.findings or []
            verified_count = sum(
                1
                for f in findings
                if f.verification_status == VerificationStatus.VERIFIED.value
            )
            published_count = sum(
                1 for f in findings if f.publish_status == PublishStatus.PUBLISHED.value
            )

            pr = run.pull_request
            repo_name = pr.repository.full_name if pr and pr.repository else None
            pr_num = pr.pr_number if pr else None

            output.append(
                ReviewRunRead(
                    id=run.id,
                    pull_request_id=run.pull_request_id,
                    pr_number=pr_num,
                    repository_full_name=repo_name,
                    commit_sha=run.commit_sha,
                    status=run.status,
                    trigger_type=run.trigger_type,
                    total_tokens=run.total_tokens,
                    total_cost_usd=float(run.total_cost_usd)
                    if run.total_cost_usd
                    else 0.0,
                    latency_seconds=float(run.latency_seconds)
                    if run.latency_seconds is not None
                    else None,
                    review_plan=run.review_plan,
                    error_log=run.error_log,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    created_at=run.created_at,
                    findings_count=len(findings),
                    verified_findings_count=verified_count,
                    published_findings_count=published_count,
                )
            )
        return output

    async def get_review_run(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
    ) -> ReviewRunRead | None:
        """Fetch single review run by UUID with aggregated findings and metadata."""
        stmt = (
            select(ReviewRun)
            .options(
                selectinload(ReviewRun.pull_request).selectinload(
                    PullRequest.repository
                ),
                selectinload(ReviewRun.findings),
                selectinload(ReviewRun.publications),
            )
            .where(ReviewRun.id == review_run_id)
        )
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return None

        findings = run.findings or []
        verified_count = sum(
            1
            for f in findings
            if f.verification_status == VerificationStatus.VERIFIED.value
        )
        published_count = sum(
            1 for f in findings if f.publish_status == PublishStatus.PUBLISHED.value
        )

        pr = run.pull_request
        repo_name = pr.repository.full_name if pr and pr.repository else None
        pr_num = pr.pr_number if pr else None

        return ReviewRunRead(
            id=run.id,
            pull_request_id=run.pull_request_id,
            pr_number=pr_num,
            repository_full_name=repo_name,
            commit_sha=run.commit_sha,
            status=run.status,
            trigger_type=run.trigger_type,
            total_tokens=run.total_tokens,
            total_cost_usd=float(run.total_cost_usd) if run.total_cost_usd else 0.0,
            latency_seconds=float(run.latency_seconds)
            if run.latency_seconds is not None
            else None,
            review_plan=run.review_plan,
            error_log=run.error_log,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            findings_count=len(findings),
            verified_findings_count=verified_count,
            published_findings_count=published_count,
        )

    async def list_findings(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID | None = None,
        verification_status: str | None = None,
        severity: str | None = None,
        issue_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewFinding]:
        """Fetch findings with attached evidence items and optional filtering."""
        stmt = (
            select(Finding)
            .options(selectinload(Finding.evidence_items))
            .order_by(desc(Finding.created_at))
        )
        if review_run_id is not None:
            stmt = stmt.where(Finding.review_run_id == review_run_id)
        if verification_status is not None:
            stmt = stmt.where(
                Finding.verification_status == verification_status.upper()
            )
        if severity is not None:
            stmt = stmt.where(Finding.severity == severity.upper())
        if issue_type is not None:
            stmt = stmt.where(Finding.issue_type == issue_type.upper())

        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        orm_findings = result.scalars().all()

        return [orm_to_finding(f) for f in orm_findings]

    async def list_findings_for_run(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
        verification_status: str | None = None,
        severity: str | None = None,
        issue_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewFinding]:
        """Fetch canonical findings for a given review run with attached evidence items."""
        stmt = (
            select(Finding)
            .options(selectinload(Finding.evidence_items))
            .where(Finding.review_run_id == review_run_id)
            .order_by(Finding.line_number.asc())
        )
        if verification_status is not None:
            stmt = stmt.where(
                Finding.verification_status == verification_status.upper()
            )
        if severity is not None:
            stmt = stmt.where(Finding.severity == severity.upper())
        if issue_type is not None:
            stmt = stmt.where(Finding.issue_type == issue_type.upper())

        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        orm_findings = result.scalars().all()

        return [orm_to_finding(f) for f in orm_findings]

    async def get_finding(
        self,
        session: AsyncSession,
        finding_id: uuid.UUID,
    ) -> ReviewFinding | None:
        """Fetch single finding by UUID with attached evidence items."""
        stmt = (
            select(Finding)
            .options(selectinload(Finding.evidence_items))
            .where(Finding.id == finding_id)
        )
        result = await session.execute(stmt)
        orm_finding = result.scalar_one_or_none()
        if orm_finding is None:
            return None
        return orm_to_finding(orm_finding)

    async def list_evidence_for_run(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
    ) -> list[EvidenceModel]:
        """Fetch all evidence items persisted for a review run."""
        stmt = (
            select(EvidenceItem)
            .where(EvidenceItem.review_run_id == review_run_id)
            .order_by(EvidenceItem.created_at.asc())
        )
        result = await session.execute(stmt)
        items = result.scalars().all()
        return [orm_to_evidence(item) for item in items]

    async def list_evidence_for_finding(
        self,
        session: AsyncSession,
        finding_id: uuid.UUID,
    ) -> list[EvidenceModel]:
        """Fetch all evidence items attached to a specific finding."""
        stmt = (
            select(EvidenceItem)
            .where(EvidenceItem.finding_id == finding_id)
            .order_by(EvidenceItem.start_line.asc())
        )
        result = await session.execute(stmt)
        items = result.scalars().all()
        return [orm_to_evidence(item) for item in items]

    async def list_publications_for_run(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
    ) -> list[PublicationResult]:
        """Fetch publication audit records for a review run converted to PublicationResult."""
        stmt = (
            select(ReviewPublication)
            .where(ReviewPublication.review_run_id == review_run_id)
            .order_by(ReviewPublication.created_at.asc())
        )
        result = await session.execute(stmt)
        pubs = result.scalars().all()

        return [
            PublicationResult(
                finding_id=p.finding_id,
                idempotency_key=p.idempotency_key,
                status=PublishStatus(p.publication_status),
                github_comment_id=p.github_comment_id,
                github_review_id=p.github_review_id,
                published_at=p.published_at,
                failure_category=p.failure_category,
                failure_message=p.failure_message,
                is_duplicate=False,
            )
            for p in pubs
        ]

    async def list_feedback(
        self,
        session: AsyncSession,
        filter_params: FeedbackFilter | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FeedbackResponse]:
        """Query reviewer feedback records with optional filtering."""
        stmt = select(ReviewFeedback).order_by(desc(ReviewFeedback.created_at))
        if filter_params:
            if filter_params.repository_id is not None:
                stmt = stmt.where(
                    ReviewFeedback.repository_id == filter_params.repository_id
                )
            if filter_params.pr_number is not None:
                stmt = stmt.where(ReviewFeedback.pr_number == filter_params.pr_number)
            if filter_params.finding_id is not None:
                stmt = stmt.where(ReviewFeedback.finding_id == filter_params.finding_id)
            if filter_params.review_run_id is not None:
                stmt = stmt.where(
                    ReviewFeedback.review_run_id == filter_params.review_run_id
                )
            if filter_params.feedback_type is not None:
                stmt = stmt.where(
                    ReviewFeedback.feedback_type == str(filter_params.feedback_type)
                )

        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        feedbacks = result.scalars().all()

        return [
            FeedbackResponse(
                id=f.id,
                finding_id=f.finding_id,
                review_run_id=f.review_run_id,
                repository_id=f.repository_id,
                pr_number=f.pr_number,
                github_comment_id=f.github_comment_id,
                github_review_id=f.github_review_id,
                feedback_type=FeedbackType(f.feedback_type),
                feedback_source=FeedbackSource(f.feedback_source),
                reviewer_username=f.reviewer_username,
                comment_body=f.comment_body,
                extra_metadata=f.extra_metadata,
                created_at=f.created_at,
            )
            for f in feedbacks
        ]

    async def get_feedback_by_id(
        self,
        session: AsyncSession,
        feedback_id: uuid.UUID,
    ) -> FeedbackResponse | None:
        """Fetch single feedback record by UUID."""
        stmt = select(ReviewFeedback).where(ReviewFeedback.id == feedback_id)
        result = await session.execute(stmt)
        f = result.scalar_one_or_none()
        if f is None:
            return None

        return FeedbackResponse(
            id=f.id,
            finding_id=f.finding_id,
            review_run_id=f.review_run_id,
            repository_id=f.repository_id,
            pr_number=f.pr_number,
            github_comment_id=f.github_comment_id,
            github_review_id=f.github_review_id,
            feedback_type=FeedbackType(f.feedback_type),
            feedback_source=FeedbackSource(f.feedback_source),
            reviewer_username=f.reviewer_username,
            comment_body=f.comment_body,
            extra_metadata=f.extra_metadata,
            created_at=f.created_at,
        )
