"""Asynchronous background worker tasks.

Defines the review_pull_request_job task entry point executed by ARQ workers.
Orchestrates GitHub App authentication, PR metadata retrieval, changed file inspection,
unified diff parsing, and commit SHA consistency verification.
"""

import logging
from typing import Any

from arq import Retry
from pydantic import ValidationError

from app.core.config import get_settings
from app.github.errors import (
    GitHubAuthenticationError,
    GitHubCommitMismatchError,
    GitHubConfigurationError,
    GitHubDiffTooLargeError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubServerError,
)
from app.schemas.job import ReviewJobPayload, ReviewJobResult
from app.services.github_service import GitHubService
from app.services.workspace_errors import (
    GitCommandError,
    GitTimeoutError,
    WorkspaceCommitMismatchError,
    WorkspaceDiskSpaceError,
    WorkspaceError,
    WorkspacePathTraversalError,
    WorkspaceSizeLimitError,
)
from app.services.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


async def review_pull_request_job(
    ctx: dict[str, Any],
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    """Execute asynchronous review job with PR context extraction.

    Validates the job payload contract, authenticates as the GitHub App,
    retrieves PR metadata, files, and diff, parses diff coordinates,
    verifies head commit SHA consistency, and returns an execution result.

    Args:
        ctx: ARQ worker context containing job_id, job_try, redis, github_service, etc.
        payload: Serialized ReviewJobPayload dictionary or JSON string.

    Returns:
        dict[str, Any]: Execution result contract matching ReviewJobResult.

    Raises:
        Retry: When a transient failure (network, 5xx, rate limit) is encountered.
        GitHubCommitMismatchError: When the retrieved PR head SHA differs from expected.
        ValueError: When the payload fails schema validation (non-retryable).
    """
    job_id = str(ctx.get("job_id", "unknown-job-id"))
    job_try = int(ctx.get("job_try", 1))

    # 1. Parse and validate job payload contract
    try:
        if isinstance(payload, str):
            job_payload = ReviewJobPayload.model_validate_json(payload)
        elif isinstance(payload, dict):
            # Check for simulated test retry directive
            if payload.get("_simulate_transient_failure") and job_try < 2:
                logger.warning(
                    "Simulating transient failure for retry test: job_id=%s, try=%d",
                    job_id,
                    job_try,
                )
                raise Retry(defer=1)

            clean_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
            job_payload = ReviewJobPayload.model_validate(clean_payload)
        else:
            raise ValueError(f"Unsupported payload type: {type(payload)}")
    except ValidationError as exc:
        logger.error(
            "Worker rejected malformed job payload: job_id=%s, error=%s",
            job_id,
            exc,
        )
        raise ValueError(f"Malformed ReviewJobPayload: {exc}") from exc

    # 2. Structured, safe logging of job execution start
    logger.info(
        "Worker started review job: job_id=%s, try=%d, repo=%s, pr=#%d, head_sha=%s, delivery_id=%s",
        job_id,
        job_try,
        job_payload.repository_full_name,
        job_payload.pr_number,
        job_payload.head_sha,
        job_payload.delivery_id,
    )

    # 3. Pull Request Context Extraction (Phase 1.8)
    github_service: GitHubService | None = ctx.get("github_service")
    if github_service is None:
        github_service = GitHubService()

    settings = get_settings()
    context_extracted = False

    # Execute context extraction if service is configured or explicitly injected
    if github_service.is_configured() or "github_service" in ctx:
        try:
            pr_context = await github_service.get_pull_request_context(
                repo_full_name=job_payload.repository_full_name,
                pr_number=job_payload.pr_number,
                expected_head_sha=job_payload.head_sha,
                expected_base_sha=job_payload.base_sha,
                installation_id=job_payload.installation_id,
            )
            context_extracted = True
            logger.info(
                "Worker successfully extracted PR context: job_id=%s, repo=%s, pr=#%d, files=%d, diff_hunks=%d",
                job_id,
                job_payload.repository_full_name,
                job_payload.pr_number,
                len(pr_context.files),
                pr_context.parsed_diff.total_hunks,
            )
        except GitHubCommitMismatchError as exc:
            logger.error(
                "Worker detected commit SHA mismatch: job_id=%s, expected=%s, retrieved=%s",
                job_id,
                exc.expected_sha,
                exc.retrieved_sha,
            )
            raise
        except (GitHubRateLimitError, GitHubServerError, GitHubNetworkError) as exc:
            logger.warning(
                "Transient GitHub failure during PR context extraction: job_id=%s, try=%d, error=%s; triggering retry",
                job_id,
                job_try,
                exc,
            )
            retry_delay = getattr(settings, "ARQ_RETRY_DELAY_SECONDS", 10)
            raise Retry(defer=retry_delay) from exc
        except (
            GitHubAuthenticationError,
            GitHubPermissionError,
            GitHubNotFoundError,
            GitHubConfigurationError,
            GitHubResponseError,
            GitHubDiffTooLargeError,
        ) as exc:
            logger.error(
                "Non-retryable GitHub failure during PR context extraction: job_id=%s, error=%s",
                job_id,
                exc,
            )
            raise
    else:
        logger.info(
            "GitHub App credentials not configured; worker acknowledged job without external API call (job_id=%s)",
            job_id,
        )

    # 4. Local Repository Workspace Preparation (Phase 1.9)
    workspace_prepared = False
    workspace_manager: WorkspaceManager | None = ctx.get("workspace_manager")

    should_prepare = False
    if workspace_manager is not None:
        should_prepare = workspace_manager.is_configured()
    elif settings.is_github_app_configured and context_extracted:
        workspace_manager = WorkspaceManager()
        should_prepare = workspace_manager.is_configured()

    if should_prepare and workspace_manager is not None:
        repo_id = job_payload.repository_id or (
            pr_context.repository_id if context_extracted else 1
        )
        try:
            async with workspace_manager.prepare(
                repository_id=repo_id,
                repository_full_name=job_payload.repository_full_name,
                pr_number=job_payload.pr_number,
                head_sha=job_payload.head_sha,
                base_sha=job_payload.base_sha,
                installation_id=job_payload.installation_id,
            ) as workspace_ctx:
                workspace_prepared = True
                logger.info(
                    "Worker prepared isolated workspace: job_id=%s, path=%s, head_sha=%s, size=%d bytes",
                    job_id,
                    workspace_ctx.workspace_path,
                    workspace_ctx.actual_head_sha,
                    workspace_ctx.size_bytes,
                )
                # Phase 2.1: Execute containerized static analysis if enabled
                if getattr(settings, "STATIC_ANALYSIS_ENABLED", True):
                    from app.static_analysis.service import StaticAnalysisService

                    sa_service: StaticAnalysisService | None = ctx.get(
                        "static_analysis_service"
                    )
                    if sa_service is None and getattr(
                        settings, "DOCKER_SANDBOX_ENABLED", True
                    ):
                        sa_service = StaticAnalysisService(settings=settings)

                    if sa_service is not None and sa_service.is_docker_available():
                        try:
                            static_results = await sa_service.run_all(workspace_ctx)
                            pa_status = (
                                static_results.pip_audit.execution_status.value
                                if static_results.pip_audit
                                else "NOT_RUN"
                            )
                            pa_count = (
                                len(static_results.pip_audit.findings)
                                if static_results.pip_audit
                                else 0
                            )
                            logger.info(
                                "Worker completed static analysis: job_id=%s, semgrep=%s (findings=%d), "
                                "bandit=%s (findings=%d), pip-audit=%s (findings=%d)",
                                job_id,
                                static_results.semgrep.execution_status.value,
                                len(static_results.semgrep.findings),
                                static_results.bandit.execution_status.value,
                                len(static_results.bandit.findings),
                                pa_status,
                                pa_count,
                            )
                        except Exception as sa_exc:
                            logger.warning(
                                "Non-blocking static analysis error: job_id=%s, error=%s",
                                job_id,
                                sa_exc,
                            )
        except GitTimeoutError as exc:
            logger.warning(
                "Transient Git timeout during workspace checkout: job_id=%s, try=%d, error=%s; triggering retry",
                job_id,
                job_try,
                exc,
            )
            retry_delay = getattr(settings, "ARQ_RETRY_DELAY_SECONDS", 10)
            raise Retry(defer=retry_delay) from exc
        except (
            WorkspaceCommitMismatchError,
            WorkspacePathTraversalError,
            WorkspaceSizeLimitError,
            WorkspaceDiskSpaceError,
            GitCommandError,
            WorkspaceError,
        ) as exc:
            logger.error(
                "Non-retryable workspace failure during checkout: job_id=%s, error=%s",
                job_id,
                exc,
            )
            raise

    # 5. Construct and return structured execution result
    final_status = "acknowledged"

    result = ReviewJobResult(
        job_id=job_id,
        delivery_id=job_payload.delivery_id,
        repository_full_name=job_payload.repository_full_name,
        pr_number=job_payload.pr_number,
        head_sha=job_payload.head_sha,
        status=final_status,
    )

    logger.info(
        "Worker completed review job: job_id=%s, delivery_id=%s, status=%s, context_extracted=%s, workspace_prepared=%s",
        job_id,
        job_payload.delivery_id,
        result.status,
        context_extracted,
        workspace_prepared,
    )

    return dict(result.model_dump(mode="json"))
