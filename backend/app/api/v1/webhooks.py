"""GitHub webhook ingestion API endpoint.

Receives GitHub HTTP webhook events, enforces HMAC-SHA256 signature verification,
coordinates delivery idempotency, and returns 202 Accepted for valid PR events.
"""

import logging
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.redis import get_redis_session
from app.database.session import get_db_session
from app.github.verifier import verify_github_signature
from app.schemas.webhook import WebhookResponse
from app.services.queue_service import ReviewJobQueueService
from app.services.webhook_service import WebhookService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def get_webhook_service() -> WebhookService:
    """Dependency provider for WebhookService."""
    return WebhookService()


def get_queue_service() -> ReviewJobQueueService:
    """Dependency provider for ReviewJobQueueService."""
    return ReviewJobQueueService()


@router.post(
    "/github",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="GitHub Webhook Ingestion",
    description=(
        "Authenticates GitHub webhook payloads using HMAC-SHA256 signatures, "
        "enforces delivery idempotency, and accepts pull request events."
    ),
    responses={
        status.HTTP_202_ACCEPTED: {
            "description": "Webhook received and verified successfully.",
            "model": WebhookResponse,
        },
        status.HTTP_400_BAD_REQUEST: {
            "description": "Missing required GitHub headers.",
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid HMAC-SHA256 signature.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Malformed pull_request event payload.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Review job queue unavailable.",
        },
    },
)
async def handle_github_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[aioredis.Redis, Depends(get_redis_session)],
    service: Annotated[WebhookService, Depends(get_webhook_service)],
    queue_service: Annotated[ReviewJobQueueService, Depends(get_queue_service)],
    x_github_event: Annotated[
        str | None, Header(description="GitHub event type")
    ] = None,
    x_github_delivery: Annotated[
        str | None, Header(description="Unique delivery GUID")
    ] = None,
    x_hub_signature_256: Annotated[
        str | None, Header(description="HMAC-SHA256 signature")
    ] = None,
) -> WebhookResponse:
    """Ingest, authenticate, and triage GitHub webhook events."""
    # 1. Validate required headers
    if not x_hub_signature_256:
        logger.warning("Rejected webhook: Missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    if not x_github_delivery:
        logger.warning("Rejected webhook: Missing X-GitHub-Delivery header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Delivery header",
        )

    if not x_github_event:
        logger.warning("Rejected webhook: Missing X-GitHub-Event header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header",
        )

    # 2. Extract exact raw body bytes for HMAC computation
    raw_body = await request.body()

    # 3. Verify HMAC-SHA256 signature in constant time
    is_valid = verify_github_signature(
        raw_payload=raw_body,
        signature_header=x_hub_signature_256,
        secret=settings.GITHUB_WEBHOOK_SECRET,
    )
    if not is_valid:
        logger.warning(
            "Rejected webhook: Invalid HMAC signature for delivery_id=%s",
            x_github_delivery,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    # 4. Delegate to WebhookService for triage, idempotency, persistence, and enqueue
    return await service.process_webhook(
        event_type=x_github_event,
        delivery_id=x_github_delivery,
        raw_body=raw_body,
        session=db,
        redis_client=redis,
        queue_service=queue_service,
    )
