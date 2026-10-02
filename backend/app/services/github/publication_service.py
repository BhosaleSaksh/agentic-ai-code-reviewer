"""Persistence and idempotency management service for review publications.

Guarantees:
- Deterministic idempotency key generation to prevent duplicate comments on GitHub
- Audit persistence of all publication attempts, successes, and failures in PostgreSQL
- Synchronization with Finding domain model publish_status and github_comment_id
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.finding import Finding
from app.database.models.publication import ReviewPublication
from app.schemas.enums import PublishStatus

logger = logging.getLogger(__name__)


class PublicationService:
    """Manages publication audit records and enforces strict idempotency."""

    @staticmethod
    def compute_finding_idempotency_key(
        repository_id: int,
        pr_number: int,
        finding_id: uuid.UUID | str,
        commit_sha: str,
    ) -> str:
        """Generate deterministic idempotency key for an individual finding publication.

        Format: '{repository_id}:{pr_number}:{finding_id}:{commit_sha}'
        """
        return f"{repository_id}:{pr_number}:{finding_id}:{commit_sha}"

    @staticmethod
    def compute_review_idempotency_key(
        repository_id: int,
        pr_number: int,
        review_run_id: uuid.UUID | str,
        commit_sha: str,
    ) -> str:
        """Generate deterministic idempotency key for a top-level review publication.

        Format: '{repository_id}:{pr_number}:review:{review_run_id}:{commit_sha}'
        """
        return f"{repository_id}:{pr_number}:review:{review_run_id}:{commit_sha}"

    async def get_by_idempotency_key(
        self,
        session: AsyncSession,
        idempotency_key: str,
    ) -> ReviewPublication | None:
        """Retrieve existing publication record by idempotency key."""
        stmt = select(ReviewPublication).where(
            ReviewPublication.idempotency_key == idempotency_key
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_already_published(
        self,
        session: AsyncSession,
        idempotency_key: str,
    ) -> bool:
        """Check whether a publication with the given key was already successfully published."""
        pub = await self.get_by_idempotency_key(session, idempotency_key)
        return pub is not None and pub.publication_status == PublishStatus.PUBLISHED

    async def record_publication(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
        repository_id: int,
        pr_number: int,
        commit_sha: str,
        idempotency_key: str,
        publication_status: PublishStatus,
        finding_id: uuid.UUID | None = None,
        github_comment_id: int | None = None,
        github_review_id: int | None = None,
        published_at: datetime | None = None,
        failure_category: str | None = None,
        failure_message: str | None = None,
        comment_payload: dict[str, Any] | None = None,
    ) -> ReviewPublication:
        """Create or update publication audit record and synchronize Finding status."""
        pub = await self.get_by_idempotency_key(session, idempotency_key)

        now = datetime.now(UTC)
        effective_published_at = (
            published_at
            if published_at is not None
            else (now if publication_status == PublishStatus.PUBLISHED else None)
        )

        if pub is None:
            pub = ReviewPublication(
                id=uuid.uuid4(),
                review_run_id=review_run_id,
                finding_id=finding_id,
                repository_id=repository_id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                idempotency_key=idempotency_key,
                github_review_id=github_review_id,
                github_comment_id=github_comment_id,
                publication_status=str(publication_status),
                published_at=effective_published_at,
                failure_category=failure_category,
                failure_message=failure_message,
                comment_payload=comment_payload,
            )
            session.add(pub)
        else:
            pub.publication_status = str(publication_status)
            if github_comment_id is not None:
                pub.github_comment_id = github_comment_id
            if github_review_id is not None:
                pub.github_review_id = github_review_id
            if effective_published_at is not None:
                pub.published_at = effective_published_at
            if failure_category is not None:
                pub.failure_category = failure_category
            if failure_message is not None:
                pub.failure_message = failure_message
            if comment_payload is not None:
                pub.comment_payload = comment_payload

        # Synchronize Finding entity if finding_id is present
        if finding_id is not None:
            finding_update_vals: dict[str, Any] = {
                "publish_status": str(publication_status)
            }
            if github_comment_id is not None:
                finding_update_vals["github_comment_id"] = github_comment_id

            await session.execute(
                update(Finding)
                .where(Finding.id == finding_id)
                .values(**finding_update_vals)
            )

        await session.flush()
        return pub

    async def get_publications_for_run(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
    ) -> list[ReviewPublication]:
        """Fetch all publication audit records for a given review run."""
        stmt = (
            select(ReviewPublication)
            .where(ReviewPublication.review_run_id == review_run_id)
            .order_by(ReviewPublication.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
