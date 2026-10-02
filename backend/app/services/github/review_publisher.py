"""Dedicated service for publishing verified code review findings to GitHub.

Orchestrates:
1. Strict Commit SHA Safety: Refuses to publish if finding SHA != current PR head SHA.
2. Independent Verification Eligibility: Only VERIFIED findings may reach GitHub.
3. Safe Comment Positioning: Anchors inline only within valid diff hunks;
   unanchored findings fall back to top-level review summary without position fabrication.
4. Idempotency & Duplicate Prevention: Guarantees no duplicate comments via unique keys.
5. Resilient Retry Strategy: Bounded exponential backoff for transient failures (rate limits, 5xx).
6. Non-retryable Failures: Immediate failure on auth, permission, or validation errors.
7. Audit Trail Persistence: Records publication status and IDs in PostgreSQL.
"""

import asyncio
import logging
import random
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.github.client import GitHubClient
from app.github.errors import (
    GitHubAuthenticationError,
    GitHubCommitMismatchError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubServerError,
    GitHubUnprocessableEntityError,
)
from app.schemas.diff import ParsedDiff
from app.schemas.enums import PublishStatus
from app.schemas.finding import ReviewFinding
from app.schemas.publication import (
    GitHubCommentPayload,
    GitHubReviewPayload,
    PublicationResult,
    ReviewPublicationSummary,
)
from app.services.github.comment_mapper import (
    format_finding_comment,
    map_finding_to_comment_payload,
)
from app.services.github.eligibility import (
    FindingEligibilityValidator,
    PositioningValidator,
)
from app.services.github.errors import (
    PublishAuthenticationError,
    PublishError,
    PublishNetworkError,
    PublishPermissionError,
    PublishRateLimitError,
    PublishServerError,
    PublishStaleCommitError,
    PublishValidationError,
)
from app.services.github.publication_service import PublicationService
from app.services.github.summary_generator import generate_review_summary

logger = logging.getLogger(__name__)


class GitHubReviewPublisher:
    """Production publisher coordinating verified findings publication to GitHub."""

    def __init__(
        self,
        github_client: GitHubClient,
        publication_service: PublicationService | None = None,
        max_retries: int = 3,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 8.0,
    ) -> None:
        """Initialize GitHubReviewPublisher.

        Args:
            github_client: Authenticated GitHub REST client.
            publication_service: Optional service for persistence and idempotency tracking.
            max_retries: Maximum number of retries for transient failures.
            base_delay_seconds: Initial backoff delay for exponential retry.
            max_delay_seconds: Maximum backoff delay cap.
        """
        self.github_client = github_client
        self.pub_service = publication_service or PublicationService()
        self.max_retries = max_retries
        self.base_delay = base_delay_seconds
        self.max_delay = max_delay_seconds

    async def _execute_with_retry(
        self,
        operation: Any,
        operation_name: str,
    ) -> Any:
        """Execute a GitHub API call with bounded exponential backoff and jitter."""
        attempt = 0
        while True:
            try:
                return await operation()
            except (GitHubAuthenticationError, PublishAuthenticationError) as exc:
                logger.error("Authentication error during %s: %s", operation_name, exc)
                raise PublishAuthenticationError(str(exc)) from exc
            except (GitHubPermissionError, PublishPermissionError) as exc:
                logger.error("Permission error during %s: %s", operation_name, exc)
                raise PublishPermissionError(str(exc)) from exc
            except (
                GitHubCommitMismatchError,
                PublishStaleCommitError,
                PublishValidationError,
            ) as exc:
                logger.error("Validation error during %s: %s", operation_name, exc)
                raise
            except GitHubNotFoundError as exc:
                logger.error("Resource not found during %s: %s", operation_name, exc)
                raise PublishValidationError(
                    f"Target GitHub resource not found: {exc}"
                ) from exc
            except GitHubUnprocessableEntityError as exc:
                logger.error(
                    "GitHub unprocessable entity during %s: %s", operation_name, exc
                )
                raise PublishValidationError(
                    f"GitHub rejected request payload as unprocessable: {exc}",
                    details={"errors": exc.errors},
                ) from exc
            except (
                GitHubRateLimitError,
                GitHubServerError,
                GitHubNetworkError,
                PublishRateLimitError,
                PublishNetworkError,
                PublishServerError,
            ) as exc:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error(
                        "Max retries (%d) exceeded for %s: %s",
                        self.max_retries,
                        operation_name,
                        exc,
                    )
                    if isinstance(exc, (GitHubRateLimitError, PublishRateLimitError)):
                        raise PublishRateLimitError(str(exc)) from exc
                    if isinstance(exc, (GitHubServerError, PublishServerError)):
                        raise PublishServerError(str(exc)) from exc
                    raise PublishNetworkError(str(exc)) from exc

                # Calculate exponential backoff with jitter
                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                jitter = random.uniform(0, 0.2 * delay)
                sleep_time = delay + jitter
                logger.warning(
                    "Transient failure in %s (attempt %d/%d). Retrying in %.2fs: %s",
                    operation_name,
                    attempt,
                    self.max_retries,
                    sleep_time,
                    exc,
                )
                await asyncio.sleep(sleep_time)
            except Exception as exc:
                logger.error("Unexpected error during %s: %s", operation_name, exc)
                raise PublishError(
                    f"Unexpected failure during {operation_name}: {exc}"
                ) from exc

    def _verify_commit_sha(self, commit_sha: str, current_pr_head_sha: str) -> None:
        """Enforce commit SHA consistency before any GitHub publication."""
        if commit_sha.strip().lower() != current_pr_head_sha.strip().lower():
            logger.error(
                "Stale commit SHA detected: finding commit %s does not match PR head %s",
                commit_sha,
                current_pr_head_sha,
            )
            raise PublishStaleCommitError(
                message=(
                    f"Publication rejected: Target commit SHA '{commit_sha}' does not match "
                    f"current PR head commit SHA '{current_pr_head_sha}'."
                ),
                expected_sha=commit_sha,
                current_head_sha=current_pr_head_sha,
            )

    async def publish_review(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
        repository_id: int,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        current_pr_head_sha: str,
        findings: list[ReviewFinding],
        parsed_diff: ParsedDiff | None = None,
        total_detected_findings: int | None = None,
    ) -> ReviewPublicationSummary:
        """Publish a full pull request review containing verified findings.

        Enforces:
        - Commit SHA consistency against current PR head
        - Strict Critic-verification eligibility
        - Diff hunk anchoring with review-summary fallback
        - Idempotent duplicate prevention
        - Full audit record persistence in PostgreSQL
        """
        # 1. Commit SHA Safety
        self._verify_commit_sha(commit_sha, current_pr_head_sha)

        # 2. Strict Finding Eligibility Check
        eligible_findings, ineligible_findings = (
            FindingEligibilityValidator.partition_findings(findings)
        )
        total_findings = (
            total_detected_findings
            if total_detected_findings is not None
            else len(findings)
        )
        rejected_count = len(ineligible_findings)

        # Record ineligible findings as SKIPPED in audit
        results: list[PublicationResult] = []
        for inelig in ineligible_findings:
            key = self.pub_service.compute_finding_idempotency_key(
                repository_id=repository_id,
                pr_number=pr_number,
                finding_id=inelig.finding_id,
                commit_sha=commit_sha,
            )
            await self.pub_service.record_publication(
                session=session,
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=key,
                publication_status=PublishStatus.SKIPPED,
                finding_id=inelig.finding_id,
                failure_category="INELIGIBLE_FINDING",
                failure_message=(
                    f"Finding status {inelig.verification_status} is not VERIFIED."
                ),
            )
            results.append(
                PublicationResult(
                    finding_id=inelig.finding_id,
                    idempotency_key=key,
                    status=PublishStatus.SKIPPED,
                    failure_category="INELIGIBLE_FINDING",
                    failure_message=f"Status {inelig.verification_status} is not VERIFIED.",
                )
            )

        # 3. Check Review-level Idempotency
        review_idempotency_key = self.pub_service.compute_review_idempotency_key(
            repository_id=repository_id,
            pr_number=pr_number,
            review_run_id=review_run_id,
            commit_sha=commit_sha,
        )
        already_published = await self.pub_service.is_already_published(
            session=session,
            idempotency_key=review_idempotency_key,
        )
        if already_published:
            existing_pub = await self.pub_service.get_by_idempotency_key(
                session=session,
                idempotency_key=review_idempotency_key,
            )
            logger.info(
                "Review run %s was already published to %s #%d. Returning idempotent result.",
                review_run_id,
                repo_full_name,
                pr_number,
            )
            return ReviewPublicationSummary(
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                github_review_id=existing_pub.github_review_id
                if existing_pub
                else None,
                total_findings=total_findings,
                verified_findings=len(eligible_findings),
                rejected_findings=rejected_count,
                published_comments=0,
                unanchored_comments=0,
                skipped_comments=len(eligible_findings),
                failed_comments=0,
                results=results,
            )

        # 4. Partition eligible findings by anchorability
        anchorable_findings, unanchored_findings = (
            PositioningValidator.partition_by_anchorable(eligible_findings, parsed_diff)
        )

        # 5. Filter out already-published individual findings
        findings_to_publish: list[ReviewFinding] = []
        for finding in anchorable_findings:
            key = self.pub_service.compute_finding_idempotency_key(
                repository_id=repository_id,
                pr_number=pr_number,
                finding_id=finding.finding_id,
                commit_sha=commit_sha,
            )
            if await self.pub_service.is_already_published(session, key):
                logger.info(
                    "Finding %s already published. Skipping duplicate comment.",
                    finding.finding_id,
                )
                results.append(
                    PublicationResult(
                        finding_id=finding.finding_id,
                        idempotency_key=key,
                        status=PublishStatus.PUBLISHED,
                        is_duplicate=True,
                    )
                )
            else:
                findings_to_publish.append(finding)

        # 6. Map anchorable comments to GitHubCommentPayloads
        comments_payload: list[GitHubCommentPayload] = [
            map_finding_to_comment_payload(f) for f in findings_to_publish
        ]

        # 7. Generate top-level review summary
        summary_markdown = generate_review_summary(
            total_findings=total_findings,
            verified_findings=eligible_findings,
            rejected_count=rejected_count,
            unanchored_findings=unanchored_findings,
            commit_sha=commit_sha,
        )

        # 8. Submit review atomically to GitHub
        review_payload = GitHubReviewPayload(
            commit_id=commit_sha,
            body=summary_markdown,
            event="COMMENT",
            comments=comments_payload,
        )

        github_review_id: int | None = None
        review_response: dict[str, Any] = {}

        try:
            review_response = await self._execute_with_retry(
                lambda: self.github_client.create_pull_request_review(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    payload=review_payload,
                ),
                operation_name=f"create_pull_request_review on {repo_full_name} #{pr_number}",
            )
            github_review_id = review_response.get("id")
            now = datetime.now(UTC)

            # Record review-level publication
            await self.pub_service.record_publication(
                session=session,
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=review_idempotency_key,
                publication_status=PublishStatus.PUBLISHED,
                github_review_id=github_review_id,
                published_at=now,
                comment_payload={"body": summary_markdown},
            )

            # Record each published finding
            for finding in findings_to_publish:
                f_key = self.pub_service.compute_finding_idempotency_key(
                    repository_id=repository_id,
                    pr_number=pr_number,
                    finding_id=finding.finding_id,
                    commit_sha=commit_sha,
                )
                await self.pub_service.record_publication(
                    session=session,
                    review_run_id=review_run_id,
                    repository_id=repository_id,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    idempotency_key=f_key,
                    publication_status=PublishStatus.PUBLISHED,
                    finding_id=finding.finding_id,
                    github_review_id=github_review_id,
                    published_at=now,
                    comment_payload={
                        "path": finding.affected_file,
                        "line": finding.line_number,
                        "side": str(finding.side),
                    },
                )
                results.append(
                    PublicationResult(
                        finding_id=finding.finding_id,
                        idempotency_key=f_key,
                        status=PublishStatus.PUBLISHED,
                        github_review_id=github_review_id,
                        published_at=now,
                    )
                )

            # Record unanchored findings as published via summary
            for finding in unanchored_findings:
                u_key = self.pub_service.compute_finding_idempotency_key(
                    repository_id=repository_id,
                    pr_number=pr_number,
                    finding_id=finding.finding_id,
                    commit_sha=commit_sha,
                )
                await self.pub_service.record_publication(
                    session=session,
                    review_run_id=review_run_id,
                    repository_id=repository_id,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    idempotency_key=u_key,
                    publication_status=PublishStatus.PUBLISHED,
                    finding_id=finding.finding_id,
                    github_review_id=github_review_id,
                    published_at=now,
                    failure_category="UNANCHORED_INLINE_FALLBACK",
                    failure_message="Included in top-level review summary (outside changed lines).",
                )
                results.append(
                    PublicationResult(
                        finding_id=finding.finding_id,
                        idempotency_key=u_key,
                        status=PublishStatus.PUBLISHED,
                        github_review_id=github_review_id,
                        published_at=now,
                        failure_category="UNANCHORED_INLINE_FALLBACK",
                        failure_message="Included in review summary.",
                    )
                )

        except Exception as exc:
            logger.error("Failed to publish PR review: %s", exc)
            # Record review-level failure
            await self.pub_service.record_publication(
                session=session,
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=review_idempotency_key,
                publication_status=PublishStatus.FAILED,
                failure_category=type(exc).__name__,
                failure_message=str(exc),
            )
            # Also record individual finding failures
            for finding in findings_to_publish:
                f_key = self.pub_service.compute_finding_idempotency_key(
                    repository_id=repository_id,
                    pr_number=pr_number,
                    finding_id=finding.finding_id,
                    commit_sha=commit_sha,
                )
                await self.pub_service.record_publication(
                    session=session,
                    review_run_id=review_run_id,
                    repository_id=repository_id,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    idempotency_key=f_key,
                    publication_status=PublishStatus.FAILED,
                    finding_id=finding.finding_id,
                    failure_category=type(exc).__name__,
                    failure_message=str(exc),
                )
                results.append(
                    PublicationResult(
                        finding_id=finding.finding_id,
                        idempotency_key=f_key,
                        status=PublishStatus.FAILED,
                        failure_category=type(exc).__name__,
                        failure_message=str(exc),
                    )
                )
            raise

        published_count = len(findings_to_publish)
        unanchored_count = len(unanchored_findings)

        return ReviewPublicationSummary(
            review_run_id=review_run_id,
            repository_id=repository_id,
            pr_number=pr_number,
            commit_sha=commit_sha,
            github_review_id=github_review_id,
            total_findings=total_findings,
            verified_findings=len(eligible_findings),
            rejected_findings=rejected_count,
            published_comments=published_count,
            unanchored_comments=unanchored_count,
            skipped_comments=len(results) - published_count - unanchored_count,
            failed_comments=0,
            results=results,
        )

    async def publish_finding_comment(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
        repository_id: int,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        current_pr_head_sha: str,
        finding: ReviewFinding,
        parsed_diff: ParsedDiff | None = None,
    ) -> PublicationResult:
        """Publish a single verified finding directly as a PR review comment.

        Enforces:
        - Finding MUST be VERIFIED
        - Finding commit_sha MUST match current PR head SHA
        - Finding MUST be anchorable in the diff
        - Deduplication via idempotency key
        """
        # 1. Commit SHA Safety
        self._verify_commit_sha(commit_sha, current_pr_head_sha)

        # 2. Finding Eligibility Check
        FindingEligibilityValidator.validate(finding)

        # 3. Idempotency Check
        idempotency_key = self.pub_service.compute_finding_idempotency_key(
            repository_id=repository_id,
            pr_number=pr_number,
            finding_id=finding.finding_id,
            commit_sha=commit_sha,
        )
        if await self.pub_service.is_already_published(session, idempotency_key):
            existing = await self.pub_service.get_by_idempotency_key(
                session, idempotency_key
            )
            logger.info(
                "Finding %s already published to %s #%d. Returning idempotent result.",
                finding.finding_id,
                repo_full_name,
                pr_number,
            )
            return PublicationResult(
                finding_id=finding.finding_id,
                idempotency_key=idempotency_key,
                status=PublishStatus.PUBLISHED,
                github_comment_id=existing.github_comment_id if existing else None,
                is_duplicate=True,
            )

        # 4. Positioning Validation
        if not PositioningValidator.can_anchor_inline(finding, parsed_diff):
            logger.warning(
                "Finding %s cannot be anchored inline in diff for %s #%d",
                finding.finding_id,
                repo_full_name,
                pr_number,
            )
            await self.pub_service.record_publication(
                session=session,
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=idempotency_key,
                publication_status=PublishStatus.SKIPPED,
                finding_id=finding.finding_id,
                failure_category="UNANCHORABLE_POSITION",
                failure_message=(
                    f"Line {finding.line_number} in '{finding.affected_file}' is not inside a diff hunk."
                ),
            )
            return PublicationResult(
                finding_id=finding.finding_id,
                idempotency_key=idempotency_key,
                status=PublishStatus.SKIPPED,
                failure_category="UNANCHORABLE_POSITION",
                failure_message="Line is not inside a diff hunk.",
            )

        # 5. Comment Formatting
        body = format_finding_comment(finding)

        # 6. Publish via GitHub Client with retry
        try:
            comment_response = await self._execute_with_retry(
                lambda: self.github_client.create_pull_request_comment(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    body=body,
                    commit_id=commit_sha,
                    path=finding.affected_file,
                    line=finding.line_number,
                    side=str(finding.side),
                ),
                operation_name=f"create_pull_request_comment on {repo_full_name} #{pr_number}",
            )
            github_comment_id = comment_response.get("id")
            now = datetime.now(UTC)

            await self.pub_service.record_publication(
                session=session,
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=idempotency_key,
                publication_status=PublishStatus.PUBLISHED,
                finding_id=finding.finding_id,
                github_comment_id=github_comment_id,
                published_at=now,
                comment_payload={
                    "path": finding.affected_file,
                    "line": finding.line_number,
                    "side": str(finding.side),
                },
            )

            return PublicationResult(
                finding_id=finding.finding_id,
                idempotency_key=idempotency_key,
                status=PublishStatus.PUBLISHED,
                github_comment_id=github_comment_id,
                published_at=now,
            )

        except Exception as exc:
            logger.error(
                "Failed to publish individual comment for finding %s: %s",
                finding.finding_id,
                exc,
            )
            await self.pub_service.record_publication(
                session=session,
                review_run_id=review_run_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=idempotency_key,
                publication_status=PublishStatus.FAILED,
                finding_id=finding.finding_id,
                failure_category=type(exc).__name__,
                failure_message=str(exc),
            )
            raise
