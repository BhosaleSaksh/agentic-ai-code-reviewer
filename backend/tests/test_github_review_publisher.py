"""Unit tests for GitHubReviewPublisher, idempotency, retry, and commit safety."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.github.client import GitHubClient
from app.orchestration.state import create_initial_review_state
from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    FileChangeType,
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)
from app.schemas.finding import ReviewFinding
from app.services.github.errors import (
    PublishAuthenticationError,
    PublishStaleCommitError,
)
from app.services.github.publication_service import PublicationService
from app.services.github.review_publisher import GitHubReviewPublisher
from app.services.review_publication_coordinator import ReviewPublicationCoordinator
from sqlalchemy.ext.asyncio import AsyncSession


def make_test_finding(
    status: VerificationStatus = VerificationStatus.VERIFIED,
    file_path: str = "src/main.py",
    line: int = 15,
) -> ReviewFinding:
    return ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file=file_path,
        line_number=line,
        side=FindingSide.RIGHT,
        title="Test Security Vulnerability",
        explanation="Untrusted input used without validation.",
        recommendation="Validate input with schema.",
        verification_status=status,
    )


@pytest.fixture
def sample_diff() -> ParsedDiff:
    hunk = DiffHunk(
        old_start=10,
        old_count=10,
        new_start=10,
        new_count=10,
        header="@@ -10,10 +10,10 @@",
        lines=[
            DiffLine(
                line_type=DiffLineType.ADDED,
                new_line_number=15,
                content="    risky_call()",
            ),
        ],
    )
    diff_file = DiffFile(
        old_path="src/main.py",
        new_path="src/main.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk],
    )
    return ParsedDiff(files=[diff_file])


@pytest.fixture
def mock_session() -> AsyncSession:
    session = AsyncMock(spec=AsyncSession)
    # mock execute returning an empty scalar_one_or_none result by default
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    return session


@pytest.mark.asyncio
async def test_verified_finding_publishes_successfully(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """1. Verified finding publishes successfully as a GitHub PR review."""
    api_calls: list[dict[str, Any]] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/pulls/10/reviews" in request.url.path
        data = request.read().decode()
        api_calls.append({"url": str(request.url), "body": data})
        return httpx.Response(200, json={"id": 99991, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="mock_token_secret", http_client=http_client)

    publisher = GitHubReviewPublisher(
        github_client=client,
        base_delay_seconds=0.01,
    )

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "a" * 40

    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[finding],
        parsed_diff=sample_diff,
    )

    assert len(api_calls) == 1
    assert summary.published_comments == 1
    assert summary.verified_findings == 1
    assert summary.github_review_id == 99991
    assert summary.failed_comments == 0


@pytest.mark.asyncio
async def test_unverified_and_rejected_findings_not_published(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """2 & 3. Unverified and rejected findings are excluded from publication."""
    api_calls: list[dict[str, Any]] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = request.read().decode()
        api_calls.append({"url": str(request.url), "body": data})
        return httpx.Response(200, json={"id": 99992, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="mock_token", http_client=http_client)
    publisher = GitHubReviewPublisher(github_client=client, base_delay_seconds=0.01)

    f_unverified = make_test_finding(VerificationStatus.UNVERIFIED, "src/main.py", 15)
    f_rejected = make_test_finding(VerificationStatus.REJECTED, "src/main.py", 15)
    commit = "a" * 40

    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[f_unverified, f_rejected],
        parsed_diff=sample_diff,
    )

    # Review was submitted, but with 0 inline comments
    assert summary.published_comments == 0
    assert summary.verified_findings == 0
    assert summary.rejected_findings == 2
    # Check that the API review payload comments array was empty
    assert (
        '"comments": []' in api_calls[0]["body"]
        or '"comments":[]' in api_calls[0]["body"]
    )


@pytest.mark.asyncio
async def test_wrong_commit_sha_prevents_publication(
    mock_session: AsyncSession,
) -> None:
    """4. Stale commit SHA raises PublishStaleCommitError and halts publication immediately."""
    client = MagicMock(spec=GitHubClient)
    publisher = GitHubReviewPublisher(github_client=client)

    finding = make_test_finding(VerificationStatus.VERIFIED)
    expected_sha = "a" * 40
    stale_sha = "b" * 40

    with pytest.raises(PublishStaleCommitError) as exc_info:
        await publisher.publish_review(
            session=mock_session,
            review_run_id=uuid.uuid4(),
            repository_id=123,
            repo_full_name="octocat/repo",
            pr_number=10,
            commit_sha=expected_sha,
            current_pr_head_sha=stale_sha,
            findings=[finding],
        )

    assert "does not match current PR head commit SHA" in str(exc_info.value)
    client.create_pull_request_review.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_line_and_invalid_file_fallback_to_summary(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """5 & 6. Unanchored lines or missing files are not faked; they fall back to the summary."""
    captured_payloads: list[dict[str, Any]] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json

        captured_payloads.append(json.loads(request.read().decode()))
        return httpx.Response(200, json={"id": 99993, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="mock_token", http_client=http_client)
    publisher = GitHubReviewPublisher(github_client=client, base_delay_seconds=0.01)

    # Line 99 is outside diff hunk
    f_invalid_line = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 99)
    # File not in diff
    f_invalid_file = make_test_finding(
        VerificationStatus.VERIFIED, "src/unrelated.py", 10
    )
    commit = "c" * 40

    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[f_invalid_line, f_invalid_file],
        parsed_diff=sample_diff,
    )

    assert summary.published_comments == 0
    assert summary.unanchored_comments == 2
    # Verify inline comments list in the submitted review payload is empty
    assert len(captured_payloads[0]["comments"]) == 0
    # Verify unanchored findings are detailed in the top-level summary body
    assert "Additional Findings (Outside Changed Lines)" in captured_payloads[0]["body"]
    assert "src/main.py:99" in captured_payloads[0]["body"]
    assert "src/unrelated.py:10" in captured_payloads[0]["body"]


@pytest.mark.asyncio
async def test_duplicate_publication_is_idempotent(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """7 & 14. Idempotency prevents duplicate comments on re-run / retry."""
    pub_service = AsyncMock(spec=PublicationService)
    # Simulate already published
    pub_service.is_already_published.return_value = True
    existing_record = MagicMock()
    existing_record.github_review_id = 88888
    pub_service.get_by_idempotency_key.return_value = existing_record
    pub_service.compute_review_idempotency_key.return_value = (
        "repo:pr:review:run:commit"
    )

    client = MagicMock(spec=GitHubClient)
    publisher = GitHubReviewPublisher(
        github_client=client, publication_service=pub_service
    )

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "d" * 40

    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[finding],
        parsed_diff=sample_diff,
    )

    # GitHub API was NOT called
    client.create_pull_request_review.assert_not_called()
    assert summary.github_review_id == 88888
    assert summary.published_comments == 0


@pytest.mark.asyncio
async def test_authentication_failure_is_not_retried(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """8. GitHub authentication failure (HTTP 401) is non-retryable and fails immediately."""
    call_count = 0

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="invalid_token", http_client=http_client)
    publisher = GitHubReviewPublisher(
        github_client=client,
        max_retries=3,
        base_delay_seconds=0.01,
    )

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "e" * 40

    with pytest.raises(PublishAuthenticationError):
        await publisher.publish_review(
            session=mock_session,
            review_run_id=uuid.uuid4(),
            repository_id=123,
            repo_full_name="octocat/repo",
            pr_number=10,
            commit_sha=commit,
            current_pr_head_sha=commit,
            findings=[finding],
            parsed_diff=sample_diff,
        )

    # Exactly 1 call was made (no retries for auth failure)
    assert call_count == 1


@pytest.mark.asyncio
async def test_rate_limit_is_retryable_and_succeeds(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """9. Rate limit (HTTP 429) triggers exponential backoff and succeeds on retry."""
    call_count = 0

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(429, json={"message": "Rate limit exceeded"})
        return httpx.Response(200, json={"id": 77777, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="mock_token", http_client=http_client)
    publisher = GitHubReviewPublisher(
        github_client=client,
        max_retries=3,
        base_delay_seconds=0.01,
        max_delay_seconds=0.05,
    )

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "f" * 40

    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[finding],
        parsed_diff=sample_diff,
    )

    assert call_count == 3
    assert summary.github_review_id == 77777
    assert summary.published_comments == 1


@pytest.mark.asyncio
async def test_network_timeout_is_retryable_and_succeeds(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """10. Network transport error triggers retry and succeeds."""
    call_count = 0

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectTimeout("Connection timed out")
        return httpx.Response(200, json={"id": 66666, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="mock_token", http_client=http_client)
    publisher = GitHubReviewPublisher(
        github_client=client,
        max_retries=3,
        base_delay_seconds=0.01,
    )

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "0" * 40

    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[finding],
        parsed_diff=sample_diff,
    )

    assert call_count == 2
    assert summary.github_review_id == 66666


@pytest.mark.asyncio
async def test_publish_single_finding_comment(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """15. Standalone single finding comment publication."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/pulls/10/comments" in request.url.path
        return httpx.Response(
            200, json={"id": 55555, "path": "src/main.py", "line": 15}
        )

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="mock_token", http_client=http_client)
    publisher = GitHubReviewPublisher(github_client=client, base_delay_seconds=0.01)

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "1" * 40

    result = await publisher.publish_finding_comment(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        finding=finding,
        parsed_diff=sample_diff,
    )

    assert result.status == PublishStatus.PUBLISHED
    assert result.github_comment_id == 55555


@pytest.mark.asyncio
async def test_review_publication_coordinator_integration(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """17. ReviewPublicationCoordinator bridges completed review state to publisher."""
    publisher = AsyncMock(spec=GitHubReviewPublisher)
    expected_summary = MagicMock()
    expected_summary.published_comments = 2
    publisher.publish_review.return_value = expected_summary

    coordinator = ReviewPublicationCoordinator(publisher=publisher)

    f1 = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    f2 = make_test_finding(VerificationStatus.VERIFIED, "src/auth.py", 20)
    commit = "2" * 40
    run_id = uuid.uuid4()

    state = create_initial_review_state(
        review_run_id=str(run_id),
        repository_id=100,
        repository_full_name="owner/repo",
        pr_number=5,
        commit_sha=commit,
        parsed_diff=sample_diff,
    )
    state["verified_findings"] = [f1.model_dump(), f2.model_dump()]

    summary = await coordinator.coordinate_review_publication(
        session=mock_session,
        state=state,
        repository_id=100,
        repo_full_name="owner/repo",
        pr_number=5,
        current_pr_head_sha=commit,
    )

    assert summary.published_comments == 2
    publisher.publish_review.assert_called_once()
    call_kwargs = publisher.publish_review.call_args.kwargs
    assert call_kwargs["commit_sha"] == commit
    assert call_kwargs["current_pr_head_sha"] == commit
    assert len(call_kwargs["findings"]) == 2


@pytest.mark.asyncio
async def test_credentials_never_appear_in_published_content(
    sample_diff: ParsedDiff,
    mock_session: AsyncSession,
) -> None:
    """16. Verification that sensitive GitHub tokens and headers never leak into comments or payloads."""
    secret_token = "ghs_SECRET_INSTALLATION_TOKEN_99999"
    captured_body = ""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.read().decode()
        # Authorization header should be sent over HTTP transport
        assert request.headers["Authorization"] == f"Bearer {secret_token}"
        return httpx.Response(200, json={"id": 11111, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token=secret_token, http_client=http_client)
    publisher = GitHubReviewPublisher(github_client=client, base_delay_seconds=0.01)

    finding = make_test_finding(VerificationStatus.VERIFIED, "src/main.py", 15)
    commit = "9" * 40

    await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=123,
        repo_full_name="octocat/repo",
        pr_number=10,
        commit_sha=commit,
        current_pr_head_sha=commit,
        findings=[finding],
        parsed_diff=sample_diff,
    )

    # The secret token must NEVER be present inside the JSON payload body or review comments
    assert secret_token not in captured_body
    assert "Bearer " not in captured_body
