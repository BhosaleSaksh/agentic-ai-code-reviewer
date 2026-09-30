"""Service for persisting normalized static analysis evidence into PostgreSQL.

Associates EvidenceModel instances with verified ReviewRun entities, enforcing
commit SHA consistency, idempotency, and transactional safety.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.evidence_item import EvidenceItem
from app.database.models.review_run import ReviewRun
from app.schemas.evidence import EvidenceModel

logger = logging.getLogger(__name__)


class EvidencePersistenceError(Exception):
    """Base exception for evidence persistence failures."""


class ReviewRunNotFoundError(EvidencePersistenceError):
    """Raised when the target ReviewRun entity is not found in the database."""


class CommitMismatchError(EvidencePersistenceError):
    """Raised when the workspace commit SHA does not match the ReviewRun commit SHA."""


class EvidencePersistenceService:
    """Transactional persistence service for canonical EvidenceModel items."""

    async def persist_evidence_batch(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
        expected_commit_sha: str,
        evidence_items: Sequence[EvidenceModel],
        replace_existing_for_tools: bool = True,
    ) -> list[EvidenceItem]:
        """Persist a batch of normalized EvidenceModels for a specific ReviewRun.

        Args:
            session: Active asynchronous database session.
            review_run_id: UUID of the associated ReviewRun.
            expected_commit_sha: Expected commit SHA to verify against ReviewRun.
            evidence_items: Sequence of normalized EvidenceModels to persist.
            replace_existing_for_tools: If True, replaces existing unassigned evidence
                for the tools being persisted to ensure idempotency.

        Returns:
            list[EvidenceItem]: List of persisted ORM entities.

        Raises:
            ReviewRunNotFoundError: If review_run_id does not exist.
            CommitMismatchError: If expected_commit_sha does not match review_run.commit_sha.
            EvidencePersistenceError: If database transaction fails.
        """
        try:
            # 1. Verify ReviewRun and exact commit SHA
            stmt = select(ReviewRun).where(ReviewRun.id == review_run_id)
            result = await session.execute(stmt)
            review_run = result.scalar_one_or_none()

            if review_run is None:
                raise ReviewRunNotFoundError(
                    f"ReviewRun {review_run_id} not found; cannot persist evidence."
                )

            if review_run.commit_sha != expected_commit_sha:
                raise CommitMismatchError(
                    f"Commit mismatch for ReviewRun {review_run_id}: "
                    f"expected {expected_commit_sha}, found {review_run.commit_sha}. "
                    "Evidence from one commit must not be attached to another."
                )

            if not evidence_items:
                logger.info(
                    "No evidence items to persist for review_run_id=%s, commit=%s",
                    review_run_id,
                    expected_commit_sha,
                )
                return []

            # 2. Idempotency: Remove previous unlinked evidence for tools being saved
            if replace_existing_for_tools:
                tools_in_batch = {
                    e.corroborating_tool for e in evidence_items if e.corroborating_tool
                }
                if tools_in_batch:
                    del_stmt = (
                        delete(EvidenceItem)
                        .where(EvidenceItem.review_run_id == review_run_id)
                        .where(EvidenceItem.finding_id.is_(None))
                        .where(EvidenceItem.corroborating_tool.in_(tools_in_batch))
                    )
                    await session.execute(del_stmt)

            # 3. Create ORM entities
            persisted_entities: list[EvidenceItem] = []
            for item in evidence_items:
                entity = EvidenceItem(
                    id=uuid.uuid4(),
                    review_run_id=review_run_id,
                    finding_id=None,
                    evidence_type=item.evidence_type.value,
                    file_path=item.file_path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    content_snippet=item.snippet,
                    rule_or_cve_id=item.rule_or_cve_id,
                    corroborating_tool=item.corroborating_tool,
                    extra_metadata=item.metadata,
                )
                session.add(entity)
                persisted_entities.append(entity)

            # 4. Flush changes to session within the ongoing transaction
            await session.flush()

            logger.info(
                "Persisted %d evidence items for review_run_id=%s, commit=%s",
                len(persisted_entities),
                review_run_id,
                expected_commit_sha,
            )
            return persisted_entities

        except (ReviewRunNotFoundError, CommitMismatchError):
            raise
        except SQLAlchemyError as exc:
            logger.error(
                "Database error while persisting evidence for review_run_id=%s: %s",
                review_run_id,
                exc,
            )
            await session.rollback()
            raise EvidencePersistenceError(
                f"Failed to persist evidence items: {exc}"
            ) from exc
