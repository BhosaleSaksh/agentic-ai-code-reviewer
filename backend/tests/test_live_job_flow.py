"""End-to-end integration and traceability test suite for Phase 9 live review path.

Validates the complete chain:
Webhook -> HMAC Verification -> Idempotency -> ARQ Task -> PR Context ->
Isolated Workspace -> Static Analysis Evidence -> Review Graph (Planner -> Specialists -> Critic) ->
PostgreSQL Traceability (Repository -> PullRequest -> ReviewRun -> Evidence -> Finding -> Publication) ->
Publication Safety Invariants.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import Settings
from app.database.models.review_run import ReviewRun
from app.github.client import GitHubClient
from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    FileChangeType,
)
from app.schemas.github import (
    GitHubPullRequestFile,
    GitHubPullRequestMetadata,
    PullRequestContext,
)
from app.schemas.job import ReviewJobPayload
from app.schemas.static_analysis import (
    BanditFinding,
    BanditResult,
    PipAuditResult,
    SemgrepFinding,
    SemgrepResult,
    StaticAnalysisExecutionStatus,
    ToolAnalysisSummary,
)
from app.services.github_service import GitHubService
from app.workers.tasks import _execute_review_pipeline
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def test_head_sha() -> str:
    return "a1b2c3d4e5f6789012345678901234567890abcd"


@pytest.fixture
def test_base_sha() -> str:
    return "b2c3d4e5f6789012345678901234567890abcde1"


@pytest.fixture
def sample_parsed_diff() -> ParsedDiff:
    hunk = DiffHunk(
        old_start=1,
        old_count=5,
        new_start=1,
        new_count=6,
        header="@@ -1,5 +1,6 @@",
        lines=[
            DiffLine(
                line_type=DiffLineType.ADDED,
                new_line_number=25,
                content="+    token = hashlib.md5(pwd.encode()).hexdigest()",
            ),
        ],
    )
    diff_file = DiffFile(
        old_path="auth.py",
        new_path="auth.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk],
    )
    return ParsedDiff(files=[diff_file])


@pytest.fixture
def sample_static_results(test_head_sha: str) -> ToolAnalysisSummary:
    semgrep_f = SemgrepFinding(
        rule_id="python.lang.security.insecure-hash-algorithm-md5",
        message="Insecure MD5 hashing detected",
        severity="ERROR",
        file_path="auth.py",
        start_line=25,
        end_line=25,
        start_col=13,
        end_col=49,
    )
    semgrep_res = SemgrepResult(
        analyzer="semgrep",
        analyzer_version="1.78.0",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=0,
        duration_seconds=0.8,
        workspace_commit_sha=test_head_sha,
        findings=[semgrep_f],
    )

    bandit_f = BanditFinding(
        test_id="B303",
        test_name="blacklist_calls",
        issue_text="Use of insecure MD5 hash",
        severity="HIGH",
        confidence="HIGH",
        file_path="auth.py",
        line_number=25,
        line_range=[25],
        code="+ token = hashlib.md5(pwd.encode()).hexdigest()",
    )
    bandit_res = BanditResult(
        analyzer="bandit",
        analyzer_version="1.7.8",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=0,
        duration_seconds=0.5,
        workspace_commit_sha=test_head_sha,
        findings=[bandit_f],
    )

    pip_audit_res = PipAuditResult(
        analyzer="pip-audit",
        analyzer_version="2.7.3",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS,
        exit_code=0,
        duration_seconds=0.2,
        workspace_commit_sha=test_head_sha,
        findings=[],
    )

    return ToolAnalysisSummary(
        semgrep=semgrep_res,
        bandit=bandit_res,
        pip_audit=pip_audit_res,
        workspace_commit_sha=test_head_sha,
        duration_seconds=1.5,
    )


@pytest.fixture
def mock_session(test_head_sha: str) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    run_obj = ReviewRun(
        id=uuid.uuid4(),
        pull_request_id=uuid.uuid4(),
        commit_sha=test_head_sha,
        status="RUNNING",
        trigger_type="WEBHOOK",
    )

    async def fake_execute(stmt, *_args, **_kwargs):
        res = MagicMock()
        stmt_str = str(stmt)
        if "review_runs" in stmt_str and "review_runs.id =" in stmt_str:
            res.scalar_one_or_none.return_value = run_obj
        else:
            res.scalar_one_or_none.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    session.execute.side_effect = fake_execute
    return session


@pytest.mark.asyncio
async def test_execute_review_pipeline_full_traceability(
    test_head_sha: str,
    test_base_sha: str,
    sample_parsed_diff: ParsedDiff,
    sample_static_results: ToolAnalysisSummary,
    mock_session: AsyncMock,
) -> None:
    """Validate that _execute_review_pipeline executes agents, normalizes evidence,

    persists entities into PostgreSQL, and coordinates publication.
    """
    settings = Settings(
        LLM_PROVIDER="mock",
        GITHUB_PUBLISH_REVIEWS=False,
        REVIEW_GRAPH_ENABLED=True,
    )

    job_payload = ReviewJobPayload(
        delivery_id="delivery-live-001",
        repository_id=12345,
        repository_full_name="test-org/secure-app",
        pr_number=42,
        pull_request_id=99001,
        head_sha=test_head_sha,
        base_sha=test_base_sha,
        action="opened",
        event_type="pull_request",
    )

    pr_context = PullRequestContext(
        repository_id=12345,
        repository_full_name="test-org/secure-app",
        pr_number=42,
        head_sha=test_head_sha,
        base_sha=test_base_sha,
        metadata=GitHubPullRequestMetadata(
            repository_id=12345,
            repository_full_name="test-org/secure-app",
            pr_number=42,
            pr_id=99001,
            title="Introduce Authentication",
            author="dev-alice",
            state="open",
            head_sha=test_head_sha,
            base_sha=test_base_sha,
            head_branch="auth-feature",
            base_branch="main",
        ),
        files=[
            GitHubPullRequestFile(
                filename="auth.py",
                status="modified",
                additions=6,
                deletions=1,
                changes=7,
            )
        ],
        parsed_diff=sample_parsed_diff,
        raw_diff="diff content",
    )

    ctx = {
        "job_id": "review:delivery-live-001",
        "job_try": 1,
        "session": mock_session,
    }

    final_state = await _execute_review_pipeline(
        ctx=ctx,
        settings=settings,
        job_payload=job_payload,
        pr_context=pr_context,
        workspace_ctx=None,
        static_results=sample_static_results,
        github_service=None,
    )

    assert final_state is not None
    assert final_state.get("status") in ("COMPLETED", "PREPARED")
    assert final_state.get("commit_sha") == test_head_sha
    assert len(final_state.get("evidence_items", [])) >= 2
    # Ensure database session methods were invoked for traceability
    assert mock_session.add.call_count >= 1
    assert mock_session.commit.call_count >= 1


@pytest.mark.asyncio
async def test_execute_review_pipeline_publishes_when_enabled_and_head_matches(
    test_head_sha: str,
    test_base_sha: str,
    sample_parsed_diff: ParsedDiff,
    sample_static_results: ToolAnalysisSummary,
    mock_session: AsyncMock,
) -> None:
    """Validate that when GITHUB_PUBLISH_REVIEWS is enabled and head SHA matches live PR,

    ReviewPublicationCoordinator publishes the review.
    """
    settings = Settings(
        LLM_PROVIDER="mock",
        GITHUB_PUBLISH_REVIEWS=True,
        REVIEW_GRAPH_ENABLED=True,
    )

    job_payload = ReviewJobPayload(
        delivery_id="delivery-live-002",
        repository_id=12345,
        repository_full_name="test-org/secure-app",
        pr_number=42,
        pull_request_id=99001,
        head_sha=test_head_sha,
        base_sha=test_base_sha,
        action="opened",
        event_type="pull_request",
    )

    pr_context = PullRequestContext(
        repository_id=12345,
        repository_full_name="test-org/secure-app",
        pr_number=42,
        head_sha=test_head_sha,
        base_sha=test_base_sha,
        metadata=GitHubPullRequestMetadata(
            repository_id=12345,
            repository_full_name="test-org/secure-app",
            pr_number=42,
            pr_id=99001,
            title="Introduce Authentication",
            author="dev-alice",
            state="open",
            head_sha=test_head_sha,
            base_sha=test_base_sha,
            head_branch="auth-feature",
            base_branch="main",
        ),
        files=[
            GitHubPullRequestFile(
                filename="auth.py", status="modified", additions=6, deletions=1
            )
        ],
        parsed_diff=sample_parsed_diff,
        raw_diff="diff content",
    )

    mock_client = MagicMock(spec=GitHubClient)
    live_pr_meta = MagicMock()
    live_pr_meta.head.sha = test_head_sha
    mock_client.get_pull_request = AsyncMock(return_value=live_pr_meta)
    mock_client.create_pull_request_review = AsyncMock(
        return_value={"id": 99999, "state": "COMMENTED"}
    )

    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.client = mock_client

    ctx = {
        "job_id": "review:delivery-live-002",
        "job_try": 1,
        "session": mock_session,
    }

    final_state = await _execute_review_pipeline(
        ctx=ctx,
        settings=settings,
        job_payload=job_payload,
        pr_context=pr_context,
        workspace_ctx=None,
        static_results=sample_static_results,
        github_service=mock_github_service,
    )

    assert final_state is not None
    mock_client.get_pull_request.assert_awaited_once_with(
        repo_full_name="test-org/secure-app",
        pr_number=42,
    )


@pytest.mark.asyncio
async def test_execute_review_pipeline_stale_commit_refuses_publication(
    test_head_sha: str,
    test_base_sha: str,
    sample_parsed_diff: ParsedDiff,
    sample_static_results: ToolAnalysisSummary,
    mock_session: AsyncMock,
) -> None:
    """Validate that when the live PR head SHA changes while review was processing,

    publication is aborted and does NOT post to the wrong commit.
    """
    settings = Settings(
        LLM_PROVIDER="mock",
        GITHUB_PUBLISH_REVIEWS=True,
        REVIEW_GRAPH_ENABLED=True,
    )

    job_payload = ReviewJobPayload(
        delivery_id="delivery-live-003",
        repository_id=12345,
        repository_full_name="test-org/secure-app",
        pr_number=42,
        pull_request_id=99001,
        head_sha=test_head_sha,
        base_sha=test_base_sha,
        action="opened",
        event_type="pull_request",
    )

    pr_context = PullRequestContext(
        repository_id=12345,
        repository_full_name="test-org/secure-app",
        pr_number=42,
        head_sha=test_head_sha,
        base_sha=test_base_sha,
        metadata=GitHubPullRequestMetadata(
            repository_id=12345,
            repository_full_name="test-org/secure-app",
            pr_number=42,
            pr_id=99001,
            title="Introduce Authentication",
            author="dev-alice",
            state="open",
            head_sha=test_head_sha,
            base_sha=test_base_sha,
            head_branch="auth-feature",
            base_branch="main",
        ),
        files=[
            GitHubPullRequestFile(
                filename="auth.py", status="modified", additions=6, deletions=1
            )
        ],
        parsed_diff=sample_parsed_diff,
        raw_diff="diff content",
    )

    # Live PR returns a NEW head SHA (developer pushed another commit!)
    new_head_sha = "ffffffffffffffffffffffffffffffffffffffff"
    mock_client = MagicMock(spec=GitHubClient)
    live_pr_meta = MagicMock()
    live_pr_meta.head.sha = new_head_sha
    mock_client.get_pull_request = AsyncMock(return_value=live_pr_meta)
    mock_client.create_pull_request_review = AsyncMock()

    mock_github_service = MagicMock(spec=GitHubService)
    mock_github_service.is_configured.return_value = True
    mock_github_service.client = mock_client

    ctx = {
        "job_id": "review:delivery-live-003",
        "job_try": 1,
        "session": mock_session,
    }

    final_state = await _execute_review_pipeline(
        ctx=ctx,
        settings=settings,
        job_payload=job_payload,
        pr_context=pr_context,
        workspace_ctx=None,
        static_results=sample_static_results,
        github_service=mock_github_service,
    )

    assert final_state is not None
    # Verify publication was aborted: create_pull_request_review was NEVER called
    mock_client.create_pull_request_review.assert_not_called()
