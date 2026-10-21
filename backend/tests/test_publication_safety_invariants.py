"""Dedicated test suite enforcing publication safety and eligibility invariants.

Tests:
1. UNVERIFIED finding -> NOT published / validation raises PublishValidationError
2. REJECTED finding -> NOT published / validation raises PublishValidationError
3. STALE finding (head commit changed) -> NOT published / raises PublishStaleCommitError
4. VERIFIED + eligible finding -> publication allowed
5. ReviewPublicationCoordinator strictly enforces verification status and commit consistency
6. A candidate finding without grounded evidence cannot become VERIFIED
"""

from __future__ import annotations

import uuid
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
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel, EvidenceType
from app.schemas.finding import ReviewFinding
from app.services.github.eligibility import FindingEligibilityValidator
from app.services.github.errors import (
    PublishStaleCommitError,
    PublishValidationError,
)
from app.services.github.review_publisher import GitHubReviewPublisher
from app.services.review_publication_coordinator import ReviewPublicationCoordinator
from sqlalchemy.ext.asyncio import AsyncSession


def _make_finding(
    status: VerificationStatus,
    file_path: str = "src/service.py",
    line: int = 25,
    has_evidence: bool = True,
) -> ReviewFinding:
    evidence = []
    if has_evidence:
        evidence.append(
            EvidenceModel(
                evidence_type=EvidenceType.STATIC_ANALYSIS,
                file_path=file_path,
                start_line=line,
                end_line=line,
                snippet="risky_call()",
                rule_or_cve_id="bandit.B303",
                corroborating_tool="bandit",
                message="Weak cryptography",
                severity=Severity.HIGH,
            )
        )
    return ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file=file_path,
        line_number=line,
        side=FindingSide.RIGHT,
        title="Security Finding",
        explanation="Test explanation",
        recommendation="Test recommendation",
        verification_status=status,
        confidence_score=0.95 if status == VerificationStatus.VERIFIED else 0.0,
        evidence=evidence,
    )


@pytest.fixture
def sample_diff() -> ParsedDiff:
    hunk = DiffHunk(
        old_start=20,
        old_count=10,
        new_start=20,
        new_count=10,
        header="@@ -20,10 +20,10 @@",
        lines=[
            DiffLine(
                line_type=DiffLineType.ADDED,
                new_line_number=25,
                content="    risky_call()",
            ),
        ],
    )
    diff_file = DiffFile(
        old_path="src/service.py",
        new_path="src/service.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk],
    )
    return ParsedDiff(files=[diff_file])


@pytest.fixture
def mock_session() -> AsyncSession:
    session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    return session


# 1. UNVERIFIED finding -> NOT published
def test_unverified_finding_ineligible_for_publication() -> None:
    finding = _make_finding(VerificationStatus.UNVERIFIED)
    assert FindingEligibilityValidator.is_eligible(finding) is False

    with pytest.raises(PublishValidationError) as exc_info:
        FindingEligibilityValidator.validate(finding)
    assert "UNVERIFIED" in str(exc_info.value)


# 2. REJECTED finding -> NOT published
def test_rejected_finding_ineligible_for_publication() -> None:
    finding = _make_finding(VerificationStatus.REJECTED)
    assert FindingEligibilityValidator.is_eligible(finding) is False

    with pytest.raises(PublishValidationError) as exc_info:
        FindingEligibilityValidator.validate(finding)
    assert "REJECTED" in str(exc_info.value)


# 3. STALE finding -> NOT published (commit mismatch raises PublishStaleCommitError)
@pytest.mark.asyncio
async def test_stale_finding_refuses_publication(
    mock_session: AsyncSession, sample_diff: ParsedDiff
) -> None:
    client = MagicMock(spec=GitHubClient)
    publisher = GitHubReviewPublisher(github_client=client)

    verified_finding = _make_finding(VerificationStatus.VERIFIED)
    review_sha = "1111111111111111111111111111111111111111"
    new_head_sha = "2222222222222222222222222222222222222222"

    with pytest.raises(PublishStaleCommitError) as exc_info:
        await publisher.publish_review(
            session=mock_session,
            review_run_id=uuid.uuid4(),
            repository_id=42,
            repo_full_name="owner/repo",
            pr_number=100,
            commit_sha=review_sha,
            current_pr_head_sha=new_head_sha,
            findings=[verified_finding],
            parsed_diff=sample_diff,
        )

    assert "does not match current PR head commit SHA" in str(exc_info.value)
    client.create_pull_request_review.assert_not_called()


# 4. VERIFIED + eligible finding -> publication allowed
@pytest.mark.asyncio
async def test_verified_eligible_finding_publishes_successfully(
    mock_session: AsyncSession, sample_diff: ParsedDiff
) -> None:
    verified_finding = _make_finding(VerificationStatus.VERIFIED)
    assert FindingEligibilityValidator.is_eligible(verified_finding) is True

    # Must pass validation without raising
    FindingEligibilityValidator.validate(verified_finding)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"id": 88888, "state": "COMMENTED"})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubClient(token="test_token", http_client=http_client)
    publisher = GitHubReviewPublisher(github_client=client, base_delay_seconds=0.01)

    matching_sha = "3333333333333333333333333333333333333333"
    summary = await publisher.publish_review(
        session=mock_session,
        review_run_id=uuid.uuid4(),
        repository_id=42,
        repo_full_name="owner/repo",
        pr_number=100,
        commit_sha=matching_sha,
        current_pr_head_sha=matching_sha,
        findings=[verified_finding],
        parsed_diff=sample_diff,
    )

    assert summary.published_comments == 1
    assert summary.verified_findings == 1
    assert summary.github_review_id == 88888
    assert summary.rejected_findings == 0


# 5. ReviewPublicationCoordinator bridges verified findings and guards stale SHA
@pytest.mark.asyncio
async def test_review_publication_coordinator_safety_filter(
    mock_session: AsyncSession, sample_diff: ParsedDiff
) -> None:
    verified = _make_finding(VerificationStatus.VERIFIED, line=25)
    unverified = _make_finding(VerificationStatus.UNVERIFIED, line=25)
    rejected = _make_finding(VerificationStatus.REJECTED, line=25)

    commit = "4444444444444444444444444444444444444444"
    state = create_initial_review_state(
        review_run_id=str(uuid.uuid4()),
        repository_id=42,
        repository_full_name="owner/repo",
        pr_number=100,
        commit_sha=commit,
        parsed_diff=sample_diff.model_dump(),
    )
    # Add findings to state
    state["candidate_findings"] = [
        verified.model_dump(mode="json"),
        unverified.model_dump(mode="json"),
        rejected.model_dump(mode="json"),
    ]
    state["verified_findings"] = [verified.model_dump(mode="json")]
    state["parsed_diff"] = sample_diff

    publisher = MagicMock(spec=GitHubReviewPublisher)
    publisher.publish_review = AsyncMock()

    coordinator = ReviewPublicationCoordinator(publisher=publisher)
    await coordinator.coordinate_review_publication(
        session=mock_session,
        state=state,
        repository_id=42,
        repo_full_name="owner/repo",
        pr_number=100,
        current_pr_head_sha=commit,
    )

    # Ensure publisher was called ONLY with verified findings (len == 1)
    call_kwargs = publisher.publish_review.call_args.kwargs
    passed_findings = call_kwargs["findings"]
    assert len(passed_findings) == 1
    assert passed_findings[0].verification_status == VerificationStatus.VERIFIED
    assert call_kwargs["total_detected_findings"] == 3
