"""Feedback collection service for developer responses and review evaluations.

Provides the foundational evaluation loop:
- Ingestion and persistence of reviewer actions (reactions, replies, resolutions, dismissals)
- Association with findings and review runs for academic evaluation and ablation studies
- Safe storage without leaking tokens, private keys, or credentials
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.feedback import ReviewFeedback
from app.database.models.publication import ReviewPublication
from app.schemas.enums import FeedbackSource, FeedbackType
from app.schemas.publication import FeedbackCreate, FeedbackFilter

logger = logging.getLogger(__name__)


class FeedbackService:
    """Service capturing and managing reviewer feedback on published reviews and comments."""

    async def record_feedback(
        self,
        session: AsyncSession,
        feedback: FeedbackCreate,
    ) -> ReviewFeedback:
        """Persist a reviewer feedback or reaction event.

        Args:
            session: Active database session.
            feedback: Structured feedback creation data.

        Returns:
            ReviewFeedback: The persisted feedback ORM entity.
        """
        # If finding_id is not provided, try to correlate via github_comment_id
        finding_id = feedback.finding_id
        review_run_id = feedback.review_run_id

        if finding_id is None and feedback.github_comment_id is not None:
            stmt = select(ReviewPublication).where(
                ReviewPublication.github_comment_id == feedback.github_comment_id
            )
            pub = (await session.execute(stmt)).scalar_one_or_none()
            if pub is not None:
                finding_id = pub.finding_id
                if review_run_id is None:
                    review_run_id = pub.review_run_id

        record = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=finding_id,
            review_run_id=review_run_id,
            repository_id=feedback.repository_id,
            pr_number=feedback.pr_number,
            github_comment_id=feedback.github_comment_id,
            github_review_id=feedback.github_review_id,
            feedback_type=str(feedback.feedback_type),
            feedback_source=str(feedback.feedback_source),
            reviewer_username=feedback.reviewer_username,
            comment_body=feedback.comment_body,
            extra_metadata=feedback.extra_metadata,
            created_at=datetime.now(UTC),
        )

        session.add(record)
        await session.flush()
        logger.info(
            "Recorded feedback %s for finding %s (type=%s, source=%s)",
            record.id,
            finding_id,
            record.feedback_type,
            record.feedback_source,
        )
        return record

    async def list_feedback(
        self,
        session: AsyncSession,
        filter_params: FeedbackFilter | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewFeedback]:
        """Query stored feedback events with optional filtering.

        Args:
            session: Active database session.
            filter_params: Optional filter criteria.
            limit: Maximum records to return.
            offset: Record offset for pagination.

        Returns:
            list[ReviewFeedback]: Matching feedback records.
        """
        stmt = select(ReviewFeedback).order_by(ReviewFeedback.created_at.desc())

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
        return list(result.scalars().all())

    async def get_feedback_by_id(
        self,
        session: AsyncSession,
        feedback_id: uuid.UUID,
    ) -> ReviewFeedback | None:
        """Fetch an individual feedback record by primary key."""
        stmt = select(ReviewFeedback).where(ReviewFeedback.id == feedback_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def record_webhook_feedback(
        self,
        session: AsyncSession,
        event_type: str,
        payload: dict[str, Any],
    ) -> ReviewFeedback | None:
        """Extract and record reviewer feedback from incoming GitHub webhook payloads.

        Supports:
        - pull_request_review_comment (created, deleted, edited)
        - pull_request_review (submitted, dismissed)
        - reaction (created) on review comments
        """
        action = payload.get("action", "")
        repo = payload.get("repository", {})
        repo_id = repo.get("id")
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number") or payload.get("issue", {}).get("number")
        sender = payload.get("sender", {}).get("login")

        if not repo_id or not pr_number:
            return None

        feedback_type: FeedbackType | None = None
        comment_id: int | None = None
        review_id: int | None = None
        body: str | None = None
        metadata: dict[str, Any] = {"action": action, "event": event_type}

        if event_type == "pull_request_review_comment":
            comment = payload.get("comment", {})
            comment_id = comment.get("id")
            body = comment.get("body")
            if action == "created":
                # Check if this comment is in reply to a review comment
                in_reply_to_id = comment.get("in_reply_to_id")
                if in_reply_to_id:
                    feedback_type = FeedbackType.COMMENT_REPLY
                    comment_id = in_reply_to_id
                    metadata["reply_comment_id"] = comment.get("id")
                else:
                    feedback_type = FeedbackType.COMMENT_REPLY
            elif action == "deleted":
                feedback_type = FeedbackType.COMMENT_DISMISSED

        elif event_type == "pull_request_review":
            review = payload.get("review", {})
            review_id = review.get("id")
            body = review.get("body")
            if action == "submitted":
                state = review.get("state", "").upper()
                if state == "APPROVED":
                    feedback_type = FeedbackType.FINDING_ACCEPTED
                elif state == "CHANGES_REQUESTED":
                    feedback_type = FeedbackType.FINDING_REJECTED
                else:
                    feedback_type = FeedbackType.REVIEW_SUBMITTED
            elif action == "dismissed":
                feedback_type = FeedbackType.COMMENT_DISMISSED

        elif event_type == "reaction":
            reaction = payload.get("reaction", {})
            content = reaction.get("content")
            metadata["reaction_content"] = content
            comment = payload.get("comment", {})
            comment_id = comment.get("id")
            if content in ("+1", "heart", "hooray", "rocket"):
                feedback_type = FeedbackType.REACTION_POSITIVE
            elif content in ("-1", "confused"):
                feedback_type = FeedbackType.REACTION_NEGATIVE
            else:
                feedback_type = FeedbackType.REACTION_POSITIVE

        if feedback_type is None:
            return None

        feedback_create = FeedbackCreate(
            repository_id=repo_id,
            pr_number=pr_number,
            github_comment_id=comment_id,
            github_review_id=review_id,
            feedback_type=feedback_type,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK,
            reviewer_username=sender,
            comment_body=body,
            extra_metadata=metadata,
        )

        return await self.record_feedback(session, feedback_create)
