"""Service for persisting verified and rejected code review findings into PostgreSQL.

Associates Finding entities and child EvidenceItem records with verified ReviewRun entities,
enforcing commit SHA consistency, idempotency, and transactional safety.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.finding import Finding
from app.database.models.review_run import ReviewRun
from app.schemas.finding import ReviewFinding
from app.services.evidence_persistence_service import (
    CommitMismatchError,
    ReviewRunNotFoundError,
)
from app.services.finding_mapper import finding_to_orm

logger = logging.getLogger(__name__)


class FindingPersistenceError(Exception):
    """Base exception for finding persistence failures."""


class FindingPersistenceService:
    """Transactional persistence service for canonical ReviewFinding items."""

    async def persist_findings_batch(
        self,
        session: AsyncSession,
        review_run_id: uuid.UUID,
        expected_commit_sha: str,
        findings: Sequence[ReviewFinding],
        replace_existing: bool = True,
    ) -> list[Finding]:
        """Persist a batch of verified/rejected ReviewFinding models for a specific ReviewRun.

        Args:
            session: Active asynchronous database session.
            review_run_id: UUID of the associated ReviewRun.
            expected_commit_sha: Expected commit SHA to verify against ReviewRun.
            findings: Sequence of ReviewFinding models to persist.
            replace_existing: If True, replaces existing findings for this review run.

        Returns:
            list[Finding]: List of persisted ORM entities with attached evidence items.

        Raises:
            ReviewRunNotFoundError: Target ReviewRun not found.
            CommitMismatchError: Workspace commit SHA does not match ReviewRun commit.
            FindingPersistenceError: Database or transaction failure.
        """
        try:
            # 1. Verify target ReviewRun exists and commit SHA aligns
            stmt = select(ReviewRun).where(ReviewRun.id == review_run_id)
            result = await session.execute(stmt)
            review_run = result.scalar_one_or_none()

            if review_run is None:
                raise ReviewRunNotFoundError(
                    f"Target ReviewRun {review_run_id} not found in database"
                )

            if review_run.commit_sha != expected_commit_sha:
                raise CommitMismatchError(
                    f"Commit SHA mismatch for ReviewRun {review_run_id}: "
                    f"expected '{expected_commit_sha}', review run has '{review_run.commit_sha}'"
                )

            # 2. Idempotency: Remove existing findings if requested
            if replace_existing:
                del_stmt = delete(Finding).where(Finding.review_run_id == review_run_id)
                await session.execute(del_stmt)

            if not findings:
                await session.commit()
                return []

            # 3. Convert canonical ReviewFinding schemas to ORM entities
            orm_entities: list[Finding] = [
                finding_to_orm(finding=finding, review_run_id=review_run_id)
                for finding in findings
            ]

            session.add_all(orm_entities)
            await session.commit()

            # Refresh persisted entities
            for entity in orm_entities:
                await session.refresh(entity)

            logger.info(
                "Persisted %d findings for review_run=%s, commit=%s",
                len(orm_entities),
                review_run_id,
                expected_commit_sha[:8],
            )
            return orm_entities

        except (ReviewRunNotFoundError, CommitMismatchError):
            await session.rollback()
            raise
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.error(
                "Database error persisting findings for review_run=%s: %s",
                review_run_id,
                exc,
                exc_info=True,
            )
            raise FindingPersistenceError(
                f"Failed to persist findings batch for run {review_run_id}: {exc}"
            ) from exc
        except Exception as exc:
            await session.rollback()
            logger.error(
                "Unexpected failure persisting findings for review_run=%s: %s",
                review_run_id,
                exc,
                exc_info=True,
            )
            raise FindingPersistenceError(
                f"Unexpected failure persisting findings for run {review_run_id}: {exc}"
            ) from exc
