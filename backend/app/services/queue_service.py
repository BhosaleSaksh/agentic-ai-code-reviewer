"""Queue service for submitting review jobs to ARQ Redis queue.

Provides a clean abstraction separating FastAPI route handlers from ARQ
pool management, job serialization, and error handling.
"""

import logging

from arq.connections import ArqRedis

from app.core.config import get_settings
from app.core.redis import get_arq_redis_pool
from app.schemas.job import ReviewJobPayload

logger = logging.getLogger(__name__)


class QueueEnqueueError(Exception):
    """Raised when enqueuing a job to ARQ Redis fails."""


class ReviewJobQueueService:
    """Service managing ARQ job submission and serialization."""

    def __init__(self, arq_pool: ArqRedis | None = None) -> None:
        self._arq_pool = arq_pool

    async def _get_pool(self) -> ArqRedis:
        """Return injected pool or lazily acquire application shared pool."""
        if self._arq_pool is not None:
            return self._arq_pool
        return await get_arq_redis_pool()

    async def enqueue_review_job(
        self,
        payload: ReviewJobPayload,
    ) -> str:
        """Enqueue a strongly typed ReviewJobPayload to ARQ Redis queue.

        Args:
            payload: Validated ReviewJobPayload contract.

        Returns:
            str: Unique ARQ job identifier.

        Raises:
            QueueEnqueueError: If Redis or ARQ is unreachable or enqueueing fails.
        """
        settings = get_settings()
        job_id = f"review:{payload.delivery_id}"

        logger.info(
            "Attempting to enqueue review job: job_id=%s, delivery_id=%s, repo=%s, pr=#%d",
            job_id,
            payload.delivery_id,
            payload.repository_full_name,
            payload.pr_number,
        )

        try:
            pool = await self._get_pool()
            job = await pool.enqueue_job(
                "review_pull_request_job",
                payload.model_dump(mode="json"),
                _job_id=job_id,
                _queue_name=settings.ARQ_QUEUE_NAME,
            )

            if job is None:
                logger.info(
                    "Job was already enqueued with duplicate key: job_id=%s",
                    job_id,
                )
                return job_id

            logger.info(
                "Successfully enqueued review job: job_id=%s, queue=%s",
                job.job_id,
                settings.ARQ_QUEUE_NAME,
            )
            return job.job_id

        except Exception as exc:
            logger.error(
                "Failed to enqueue review job to ARQ queue: delivery_id=%s, error=%s",
                payload.delivery_id,
                exc,
            )
            raise QueueEnqueueError(
                f"Queue enqueue failed for delivery_id={payload.delivery_id}: {exc}"
            ) from exc
