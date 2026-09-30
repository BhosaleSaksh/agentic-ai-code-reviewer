"""GitHub webhook event triage and delivery deduplication service.

Classifies incoming webhook events, ensures idempotency across Redis and
PostgreSQL, records delivery state, and returns structured response contracts.
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.webhook_delivery import WebhookDelivery
from app.schemas.job import ReviewJobPayload
from app.schemas.webhook import PullRequestWebhookPayload, WebhookResponse
from app.services.queue_service import ReviewJobQueueService

logger = logging.getLogger(__name__)

# Events and actions supported for review triggering
SUPPORTED_EVENT: str = "pull_request"
SUPPORTED_ACTIONS: frozenset[str] = frozenset({"opened", "synchronize", "reopened"})
REDIS_DELIVERY_TTL_SECONDS: int = 86400  # 24 hours per ARCHITECTURE.md line 179


class WebhookService:
    """Service handling GitHub webhook validation, triage, and idempotency."""

    @staticmethod
    def _redis_key(delivery_id: str) -> str:
        return f"webhook:delivery:{delivery_id}"

    async def is_duplicate_delivery(
        self,
        delivery_id: str,
        session: AsyncSession,
        redis_client: aioredis.Redis | None = None,
    ) -> bool:
        """Check whether the delivery ID has already been recorded in Redis or DB."""
        # 1. Check Redis cache first (fast path)
        if redis_client is not None:
            try:
                cached = await redis_client.get(self._redis_key(delivery_id))
                if cached is not None:
                    cached_str = (
                        cached.decode("utf-8")
                        if isinstance(cached, bytes)
                        else str(cached)
                    )
                    if cached_str != "failed":
                        logger.info(
                            "Webhook idempotency hit (Redis): delivery_id=%s",
                            delivery_id,
                        )
                        return True
            except Exception as exc:
                logger.warning(
                    "Redis delivery cache check failed: %s; falling back to DB",
                    exc,
                )

        # 2. Check PostgreSQL database (authoritative persistence)
        stmt = select(WebhookDelivery.status).where(
            WebhookDelivery.delivery_id == delivery_id
        )
        result = await session.execute(stmt)
        existing_status = result.scalar_one_or_none()
        if existing_status is not None and existing_status != "failed":
            logger.info(
                "Webhook idempotency hit (Database): delivery_id=%s, status=%s",
                delivery_id,
                existing_status,
            )
            return True

        return False

    async def _record_delivery(
        self,
        session: AsyncSession,
        delivery_id: str,
        event_type: str,
        delivery_status: str,
        action: str | None = None,
        repository_id: int | None = None,
        repository_full_name: str | None = None,
        pr_number: int | None = None,
        head_sha: str | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> bool:
        """Persist delivery record in PostgreSQL and cache in Redis.

        Returns True on successful persistence, or False if unique constraint collision.
        """
        stmt = select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is not None and not isinstance(record, WebhookDelivery):
            record = None

        if record is not None:
            if record.status != "failed":
                logger.info(
                    "Webhook delivery collision detected during check: delivery_id=%s, existing_status=%s",
                    delivery_id,
                    record.status,
                )
                return False
            # Update previously failed delivery record
            record.status = delivery_status
            record.event_type = event_type
            record.action = action
            record.repository_id = repository_id
            record.repository_full_name = repository_full_name
            record.pr_number = pr_number
            record.head_sha = head_sha
        else:
            record = WebhookDelivery(
                delivery_id=delivery_id,
                event_type=event_type,
                action=action,
                repository_id=repository_id,
                repository_full_name=repository_full_name,
                pr_number=pr_number,
                head_sha=head_sha,
                status=delivery_status,
            )
            session.add(record)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info(
                "Webhook delivery collision detected during commit: delivery_id=%s",
                delivery_id,
            )
            return False

        # Cache in Redis with 24-hour expiration
        if redis_client is not None:
            try:
                await redis_client.set(
                    self._redis_key(delivery_id),
                    delivery_status,
                    ex=REDIS_DELIVERY_TTL_SECONDS,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to cache delivery_id in Redis: %s",
                    exc,
                )

        return True

    async def _mark_delivery_failed(
        self,
        session: AsyncSession,
        delivery_id: str,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        """Mark delivery as failed in PostgreSQL and remove or update Redis cache."""
        try:
            stmt = select(WebhookDelivery).where(
                WebhookDelivery.delivery_id == delivery_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record is not None:
                record.status = "failed"
                await session.commit()
        except Exception as exc:
            logger.error(
                "Failed to mark delivery as failed in database: %s",
                exc,
            )
            await session.rollback()

        if redis_client is not None:
            try:
                await redis_client.delete(self._redis_key(delivery_id))
            except Exception as exc:
                logger.warning(
                    "Failed to delete Redis delivery cache on enqueue failure: %s",
                    exc,
                )

    async def process_webhook(
        self,
        event_type: str,
        delivery_id: str,
        raw_body: bytes,
        session: AsyncSession,
        redis_client: aioredis.Redis | None = None,
        queue_service: ReviewJobQueueService | None = None,
    ) -> WebhookResponse:
        """Process, validate, triage, and record an incoming GitHub webhook.

        Args:
            event_type: Value of X-GitHub-Event header.
            delivery_id: Value of X-GitHub-Delivery header.
            raw_body: Raw bytes of the webhook HTTP request body.
            session: Active database session.
            redis_client: Optional async Redis client.
            queue_service: Optional queue service for submitting review jobs.

        Returns:
            WebhookResponse: Ingestion response with status ('accepted', 'ignored', 'duplicate').
        """
        # 1. Idempotency verification
        if await self.is_duplicate_delivery(delivery_id, session, redis_client):
            return WebhookResponse(
                status="duplicate",
                delivery_id=delivery_id,
                event=event_type,
                action=None,
                message="Webhook delivery has already been processed",
            )

        # 2. Check for non-PR events (e.g. ping, push, issues)
        if event_type != SUPPORTED_EVENT:
            action_name = None
            try:
                data: dict[str, Any] = json.loads(raw_body)
                action_name = data.get("action")
            except Exception:
                pass  # payload may not be JSON for ping

            persisted = await self._record_delivery(
                session=session,
                delivery_id=delivery_id,
                event_type=event_type,
                delivery_status="ignored",
                action=action_name,
                redis_client=redis_client,
            )
            if not persisted:
                return WebhookResponse(
                    status="duplicate",
                    delivery_id=delivery_id,
                    event=event_type,
                    action=action_name,
                    message="Webhook delivery has already been processed",
                )

            logger.info(
                "Webhook event ignored: event=%s, delivery_id=%s",
                event_type,
                delivery_id,
            )
            return WebhookResponse(
                status="ignored",
                delivery_id=delivery_id,
                event=event_type,
                action=action_name,
                message=(
                    f"Event '{event_type}' ignored; only '{SUPPORTED_EVENT}' "
                    "events trigger automated code reviews"
                ),
            )

        # 3. Parse and validate pull_request event payload
        try:
            payload = PullRequestWebhookPayload.model_validate_json(raw_body)
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "Webhook payload validation failure: delivery_id=%s, error=%s",
                delivery_id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Malformed pull_request webhook payload",
            ) from exc

        # 4. Check action support (opened, synchronize, reopened)
        if payload.action not in SUPPORTED_ACTIONS:
            persisted = await self._record_delivery(
                session=session,
                delivery_id=delivery_id,
                event_type=event_type,
                delivery_status="ignored",
                action=payload.action,
                repository_id=payload.repository.id,
                repository_full_name=payload.repository.full_name,
                pr_number=payload.number,
                head_sha=payload.pull_request.head.sha,
                redis_client=redis_client,
            )
            if not persisted:
                return WebhookResponse(
                    status="duplicate",
                    delivery_id=delivery_id,
                    event=event_type,
                    action=payload.action,
                    message="Webhook delivery has already been processed",
                )

            logger.info(
                "Pull request action ignored: action=%s, repo=%s, pr=#%d, delivery_id=%s",
                payload.action,
                payload.repository.full_name,
                payload.number,
                delivery_id,
            )
            return WebhookResponse(
                status="ignored",
                delivery_id=delivery_id,
                event=event_type,
                action=payload.action,
                message=(
                    f"Action '{payload.action}' ignored; only "
                    f"{', '.join(sorted(SUPPORTED_ACTIONS))} trigger reviews"
                ),
            )

        # 5. Supported review-triggering event
        persisted = await self._record_delivery(
            session=session,
            delivery_id=delivery_id,
            event_type=event_type,
            delivery_status="accepted",
            action=payload.action,
            repository_id=payload.repository.id,
            repository_full_name=payload.repository.full_name,
            pr_number=payload.number,
            head_sha=payload.pull_request.head.sha,
            redis_client=redis_client,
        )
        if not persisted:
            return WebhookResponse(
                status="duplicate",
                delivery_id=delivery_id,
                event=event_type,
                action=payload.action,
                message="Webhook delivery has already been processed",
            )

        # 6. Enqueue review job to ARQ queue
        if queue_service is not None:
            job_payload = ReviewJobPayload(
                delivery_id=delivery_id,
                repository_id=payload.repository.id,
                repository_full_name=payload.repository.full_name,
                pr_number=payload.number,
                pull_request_id=payload.pull_request.id,
                head_sha=payload.pull_request.head.sha,
                base_sha=payload.pull_request.base.sha,
                action=payload.action,
                event_type=event_type,
                installation_id=(
                    payload.installation.id if payload.installation else None
                ),
            )
            try:
                await queue_service.enqueue_review_job(job_payload)
            except Exception as exc:
                logger.error(
                    "Review job queue enqueue failed for delivery_id=%s: %s",
                    delivery_id,
                    exc,
                )
                await self._mark_delivery_failed(
                    session=session,
                    delivery_id=delivery_id,
                    redis_client=redis_client,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Review job queue unavailable. Please retry later.",
                ) from exc

        logger.info(
            "Pull request webhook accepted: action=%s, repo=%s, pr=#%d, head_sha=%s, delivery_id=%s",
            payload.action,
            payload.repository.full_name,
            payload.number,
            payload.pull_request.head.sha,
            delivery_id,
        )
        return WebhookResponse(
            status="accepted",
            delivery_id=delivery_id,
            event=event_type,
            action=payload.action,
            message="Pull request review event accepted for processing",
        )
