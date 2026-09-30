"""ARQ worker configuration and execution settings.

Configures Redis connection, job timeouts, concurrency limits, and lifecycle
hooks for the background worker process using application Settings.
"""

import logging
from typing import Any

from arq.typing import WorkerCoroutine

from app.core.config import get_settings
from app.workers.tasks import review_pull_request_job

logger = logging.getLogger(__name__)
settings = get_settings()


async def on_startup(_ctx: dict[str, Any]) -> None:
    """Worker initialization hook executed on process startup."""
    logger.info(
        "ARQ Worker starting up: queue='%s', max_jobs=%d, job_timeout=%ds, max_retries=%d",
        settings.ARQ_QUEUE_NAME,
        settings.ARQ_MAX_JOBS,
        settings.ARQ_JOB_TIMEOUT_SECONDS,
        settings.ARQ_MAX_RETRIES,
    )


async def on_shutdown(_ctx: dict[str, Any]) -> None:
    """Worker termination hook executed on process shutdown."""
    logger.info("ARQ Worker shutting down cleanly.")


class WorkerSettings:
    """ARQ Worker configuration class discovered by CLI or custom runners."""

    # Register worker task functions
    functions: list[WorkerCoroutine] = [review_pull_request_job]
    cron_jobs: list[Any] | None = None

    # Redis connection configuration derived from centralized Settings
    redis_settings = settings.arq_redis_settings

    # Queue naming and execution boundaries
    queue_name: str = settings.ARQ_QUEUE_NAME
    max_jobs: int = settings.ARQ_MAX_JOBS
    job_timeout: int = settings.ARQ_JOB_TIMEOUT_SECONDS
    max_tries: int = settings.ARQ_MAX_RETRIES
    keep_result: int = settings.ARQ_KEEP_RESULT_SECONDS

    # Worker lifecycle callbacks
    on_startup = on_startup
    on_shutdown = on_shutdown
