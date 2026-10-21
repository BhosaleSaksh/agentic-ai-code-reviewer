"""Asynchronous background worker tasks.

Defines the review_pull_request_job task entry point executed by ARQ workers.
Orchestrates GitHub App authentication, PR metadata retrieval, changed file inspection,
unified diff parsing, and commit SHA consistency verification.
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from arq import Retry
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.models.pull_request import PullRequest
from app.database.models.repository import Repository
from app.database.models.review_run import ReviewRun
from app.database.session import async_session_factory, check_db_connection
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
from app.orchestration.review_graph import execute_review_graph
from app.orchestration.state import (
    ReviewState,
    create_initial_review_state,
    extract_candidate_findings,
    extract_verified_findings,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.job import ReviewJobPayload, ReviewJobResult
from app.services.evidence_persistence_service import EvidencePersistenceService
from app.services.finding_persistence_service import FindingPersistenceService
from app.services.github.review_publisher import GitHubReviewPublisher
from app.services.github_service import GitHubService
from app.services.review_publication_coordinator import ReviewPublicationCoordinator
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
from app.static_analysis.evidence_normalizer import normalize_tool_analysis_summary

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

                # Phase 9: End-to-end agentic review pipeline execution & DB persistence
                if (
                    getattr(settings, "REVIEW_GRAPH_ENABLED", True)
                    and context_extracted
                ):
                    await _execute_review_pipeline(
                        ctx=ctx,
                        settings=settings,
                        job_payload=job_payload,
                        pr_context=pr_context,
                        workspace_ctx=workspace_ctx,
                        static_results=static_results,
                        github_service=github_service,
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
    elif (
        getattr(settings, "REVIEW_GRAPH_ENABLED", True)
        and context_extracted
        and ctx.get("run_review_graph", False)
    ):
        await _execute_review_pipeline(
            ctx=ctx,
            settings=settings,
            job_payload=job_payload,
            pr_context=pr_context,
            workspace_ctx=None,
            static_results=None,
            github_service=github_service,
        )

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


async def _execute_review_pipeline(
    ctx: dict[str, Any],
    settings: Any,
    job_payload: ReviewJobPayload,
    pr_context: Any,
    workspace_ctx: Any | None,
    static_results: Any | None,
    github_service: GitHubService | None,
) -> ReviewState | None:
    """Execute end-to-end agentic review pipeline, database persistence, and publication."""
    logger.info(
        "Starting agentic review pipeline for job_id=%s, repo=%s, pr=#%d, head_sha=%s",
        ctx.get("job_id", "unknown"),
        job_payload.repository_full_name,
        job_payload.pr_number,
        job_payload.head_sha,
    )
    _ = workspace_ctx

    # 1. Normalize static analysis evidence
    evidence_items: list[EvidenceModel] = []
    if static_results is not None:
        try:
            evidence_items = normalize_tool_analysis_summary(static_results)
            logger.info(
                "Normalized %d static analysis evidence items", len(evidence_items)
            )
        except Exception as ev_exc:
            logger.warning("Error normalizing static analysis evidence: %s", ev_exc)

    # 2. Check Database Connectivity
    session_factory = ctx.get("db_session_factory")
    is_db_available = False
    if "session" in ctx or session_factory is not None:
        is_db_available = True
    else:
        try:
            is_db_available = await check_db_connection()
            if is_db_available:
                session_factory = async_session_factory
        except Exception:
            is_db_available = False

    run_id = uuid.uuid4()
    if is_db_available:
        try:

            async def _init_db_records(
                session: AsyncSession, default_run_id: uuid.UUID
            ) -> uuid.UUID:
                # Upsert Repository
                repo_id_val = job_payload.repository_id or getattr(
                    pr_context, "repository_id", 1
                )
                repo_stmt = select(Repository).where(
                    or_(
                        Repository.github_repo_id == repo_id_val,
                        Repository.full_name == job_payload.repository_full_name,
                    )
                )
                repo_res = await session.execute(repo_stmt)
                db_repo = repo_res.scalar_one_or_none()
                if db_repo is None:
                    base_br = "main"
                    if hasattr(pr_context, "metadata") and getattr(
                        pr_context.metadata, "base_branch", None
                    ):
                        base_br = pr_context.metadata.base_branch
                    db_repo = Repository(
                        id=uuid.uuid4(),
                        github_repo_id=repo_id_val,
                        full_name=job_payload.repository_full_name,
                        default_branch=base_br,
                        is_active=True,
                    )
                    session.add(db_repo)
                    await session.flush()

                # Upsert PullRequest
                pr_stmt = select(PullRequest).where(
                    PullRequest.repository_id == db_repo.id,
                    PullRequest.pr_number == job_payload.pr_number,
                )
                pr_res = await session.execute(pr_stmt)
                db_pr = pr_res.scalar_one_or_none()

                pr_title = (
                    pr_context.metadata.title
                    if hasattr(pr_context, "metadata")
                    and getattr(pr_context.metadata, "title", None)
                    else f"PR #{job_payload.pr_number}"
                )
                pr_author = (
                    pr_context.metadata.author
                    if hasattr(pr_context, "metadata")
                    and getattr(pr_context.metadata, "author", None)
                    else "unknown"
                )
                files_list = getattr(pr_context, "files", [])
                tot_adds = sum(getattr(f, "additions", 0) for f in files_list)
                tot_dels = sum(getattr(f, "deletions", 0) for f in files_list)

                if db_pr is None:
                    db_pr = PullRequest(
                        id=uuid.uuid4(),
                        repository_id=db_repo.id,
                        pr_number=job_payload.pr_number,
                        title=pr_title,
                        author=pr_author,
                        base_sha=job_payload.base_sha
                        or getattr(pr_context, "base_sha", "")
                        or "",
                        head_sha=job_payload.head_sha,
                        state="open",
                        additions=tot_adds,
                        deletions=tot_dels,
                        changed_files_count=len(files_list),
                    )
                    session.add(db_pr)
                    await session.flush()
                else:
                    db_pr.head_sha = job_payload.head_sha
                    db_pr.title = pr_title
                    db_pr.author = pr_author
                    if job_payload.base_sha:
                        db_pr.base_sha = job_payload.base_sha
                    await session.flush()

                # Upsert ReviewRun
                run_stmt = select(ReviewRun).where(
                    ReviewRun.pull_request_id == db_pr.id,
                    ReviewRun.commit_sha == job_payload.head_sha,
                )
                run_res = await session.execute(run_stmt)
                db_run = run_res.scalar_one_or_none()
                resolved_run_id = default_run_id
                if db_run is None:
                    db_run = ReviewRun(
                        id=default_run_id,
                        pull_request_id=db_pr.id,
                        commit_sha=job_payload.head_sha,
                        status="RUNNING",
                        trigger_type="WEBHOOK",
                    )
                    session.add(db_run)
                else:
                    db_run.status = "RUNNING"
                    resolved_run_id = db_run.id
                await session.commit()
                return resolved_run_id

            if "session" in ctx:
                run_id = await _init_db_records(ctx["session"], run_id)
            elif session_factory is not None:
                async with session_factory() as session:
                    run_id = await _init_db_records(session, run_id)
        except Exception as db_init_err:
            logger.warning("Database review run init warning: %s", db_init_err)

    # 3. Create Initial Review State
    initial_state = create_initial_review_state(
        review_run_id=str(run_id),
        repository_id=job_payload.repository_id
        or getattr(pr_context, "repository_id", 1),
        repository_full_name=job_payload.repository_full_name,
        pr_number=job_payload.pr_number,
        commit_sha=job_payload.head_sha,
        base_sha=job_payload.base_sha or getattr(pr_context, "base_sha", None),
        pr_title=getattr(pr_context.metadata, "title", None)
        if hasattr(pr_context, "metadata")
        else None,
        pr_author=getattr(pr_context.metadata, "author", None)
        if hasattr(pr_context, "metadata")
        else None,
        parsed_diff=getattr(pr_context, "parsed_diff", None),
        changed_files=[f.filename for f in getattr(pr_context, "files", [])],
        evidence_items=evidence_items,
    )

    # 4. Execute Review Graph (Planner -> Specialists -> Grounding -> Critic)
    try:
        custom_graph = ctx.get("review_graph")
        final_state = await execute_review_graph(
            initial_state=initial_state,
            graph=custom_graph,
            raise_on_failure=False,
        )
    except Exception as graph_err:
        logger.error("Review graph execution error: %s", graph_err, exc_info=True)
        final_state = initial_state
        final_state["status"] = "FAILED"
        final_state["error"] = str(graph_err)

    # 5. Persist Results into Database
    if is_db_available:
        try:

            async def _persist_results(session: AsyncSession) -> None:
                if evidence_items:
                    ev_service = EvidencePersistenceService()
                    await ev_service.persist_evidence_batch(
                        session=session,
                        review_run_id=run_id,
                        expected_commit_sha=job_payload.head_sha,
                        evidence_items=evidence_items,
                    )

                verified_findings = extract_verified_findings(final_state)
                candidate_findings = extract_candidate_findings(final_state)
                all_findings = candidate_findings or verified_findings
                if all_findings:
                    find_service = FindingPersistenceService()
                    await find_service.persist_findings_batch(
                        session=session,
                        review_run_id=run_id,
                        expected_commit_sha=job_payload.head_sha,
                        findings=all_findings,
                    )

                run_stmt = select(ReviewRun).where(ReviewRun.id == run_id)
                run_res = await session.execute(run_stmt)
                db_run = run_res.scalar_one_or_none()
                if db_run is not None:
                    db_run.status = str(final_state.get("status", "COMPLETED"))
                    raw_plan = final_state.get("review_plan")
                    if raw_plan is not None:
                        db_run.review_plan = (
                            raw_plan.model_dump()
                            if hasattr(raw_plan, "model_dump")
                            else raw_plan
                        )
                    exec_meta = final_state.get("execution_metadata", {})
                    db_run.total_tokens = int(exec_meta.get("total_tokens", 0))
                    durations = exec_meta.get("durations", {})
                    if durations and isinstance(durations, dict):
                        total_sec = sum(
                            v for v in durations.values() if isinstance(v, (int, float))
                        )
                        db_run.latency_seconds = Decimal(str(round(total_sec, 2)))
                    await session.commit()

            if "session" in ctx:
                await _persist_results(ctx["session"])
            elif session_factory is not None:
                async with session_factory() as session:
                    await _persist_results(session)
        except Exception as persist_err:
            logger.warning(
                "Database persistence of review results warning: %s", persist_err
            )

    # 6. Publish Review to GitHub if Enabled
    publish_enabled = getattr(settings, "GITHUB_PUBLISH_REVIEWS", False) or ctx.get(
        "publish_review", False
    )
    if (
        publish_enabled
        and github_service is not None
        and github_service.is_configured()
    ):
        try:
            if "/" in job_payload.repository_full_name:
                gh_client = getattr(github_service, "client", None)
                if gh_client is None:
                    gh_client = await github_service.create_client()

                # Live PR head SHA check to prevent stale publication!
                live_pr = await gh_client.get_pull_request(
                    repo_full_name=job_payload.repository_full_name,
                    pr_number=job_payload.pr_number,
                )
                current_live_head_sha = (
                    getattr(live_pr, "head_sha", None)
                    or (
                        getattr(live_pr.head, "sha", None)
                        if hasattr(live_pr, "head")
                        else None
                    )
                    or ""
                )

                publisher = GitHubReviewPublisher(github_client=gh_client)
                coordinator = ReviewPublicationCoordinator(publisher=publisher)

                async def _run_publish(session: AsyncSession) -> None:
                    pub_summary = await coordinator.coordinate_review_publication(
                        session=session,
                        state=final_state,
                        repository_id=job_payload.repository_id
                        or getattr(pr_context, "repository_id", 1),
                        repo_full_name=job_payload.repository_full_name,
                        pr_number=job_payload.pr_number,
                        current_pr_head_sha=current_live_head_sha,
                    )
                    logger.info(
                        "Review publication complete: run_id=%s, comments_published=%d, verified=%d",
                        run_id,
                        pub_summary.published_comments,
                        pub_summary.verified_findings,
                    )

                if "session" in ctx:
                    await _run_publish(ctx["session"])
                elif session_factory is not None:
                    async with session_factory() as session:
                        await _run_publish(session)
        except Exception as pub_err:
            logger.warning("Review publication warning: %s", pub_err)

    return final_state
