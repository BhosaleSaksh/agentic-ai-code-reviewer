"""Coordinator service bridging completed review workflows with the GitHub publication layer.

Operates strictly as a post-verification pipeline stage:
Workflow State (Critic Verified) -> ReviewPublicationCoordinator -> GitHubReviewPublisher -> GitHub PR Review

Guarantees:
- Specialist agents and CriticAgent NEVER publish directly.
- Only findings that have successfully passed Critic verification are eligible.
- Ensures commit SHA consistency and diff hunk positioning.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.state import (
    ReviewState,
    extract_candidate_findings,
    extract_verified_findings,
)
from app.schemas.diff import ParsedDiff
from app.schemas.publication import ReviewPublicationSummary
from app.services.github.review_publisher import GitHubReviewPublisher

logger = logging.getLogger(__name__)


class ReviewPublicationCoordinator:
    """Orchestrates publication of completed and verified review state results to GitHub."""

    def __init__(self, publisher: GitHubReviewPublisher) -> None:
        """Initialize with a configured GitHubReviewPublisher."""
        self.publisher = publisher

    async def coordinate_review_publication(
        self,
        session: AsyncSession,
        state: ReviewState,
        repository_id: int,
        repo_full_name: str,
        pr_number: int,
        current_pr_head_sha: str,
    ) -> ReviewPublicationSummary:
        """Publish verified findings from a completed review state to the target GitHub PR.

        Args:
            session: Active database session for audit persistence.
            state: Completed ReviewState resulting from LangGraph workflow.
            repository_id: GitHub repository numeric ID.
            repo_full_name: Target repository full name (owner/repo).
            pr_number: Target pull request number.
            current_pr_head_sha: Live PR head commit SHA from GitHub.

        Returns:
            ReviewPublicationSummary: Summary of publication results.
        """
        review_run_id_raw = state.get("review_run_id")
        review_run_id = (
            uuid.UUID(str(review_run_id_raw)) if review_run_id_raw else uuid.uuid4()
        )
        commit_sha = state.get("commit_sha", "")

        # Extract verified findings and total candidates
        verified_findings = extract_verified_findings(state)
        candidate_findings = extract_candidate_findings(state)
        total_detected = (
            len(candidate_findings) if candidate_findings else len(verified_findings)
        )

        # Extract parsed diff
        parsed_diff_raw = state.get("parsed_diff")
        parsed_diff: ParsedDiff | None = None
        if isinstance(parsed_diff_raw, ParsedDiff):
            parsed_diff = parsed_diff_raw
        elif isinstance(parsed_diff_raw, dict):
            parsed_diff = ParsedDiff.model_validate(parsed_diff_raw)

        logger.info(
            "Coordinating review publication: run_id=%s, repo=%s, pr=#%d, commit=%s, "
            "verified_count=%d, candidate_count=%d",
            review_run_id,
            repo_full_name,
            pr_number,
            commit_sha,
            len(verified_findings),
            total_detected,
        )

        return await self.publisher.publish_review(
            session=session,
            review_run_id=review_run_id,
            repository_id=repository_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            commit_sha=commit_sha,
            current_pr_head_sha=current_pr_head_sha,
            findings=verified_findings,
            parsed_diff=parsed_diff,
            total_detected_findings=total_detected,
        )
