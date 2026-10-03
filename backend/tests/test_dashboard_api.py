"""Comprehensive tests for Phase 6 review dashboard read endpoints and service.

Covers:
- /api/v1/dashboard/metrics
- /api/v1/repositories and /api/v1/repositories/{id}
- /api/v1/pull-requests and /api/v1/pull-requests/{id}
- /api/v1/reviews, /api/v1/reviews/{id}, /findings, /evidence, /publications, /feedback
- /api/v1/findings/{id} and /evidence
- /api/v1/feedback and /api/v1/feedback/{id}
- 404 handling, pagination, and query filtering
"""

import random
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest
from app.database.models.evidence_item import EvidenceItem
from app.database.models.feedback import ReviewFeedback
from app.database.models.finding import Finding
from app.database.models.publication import ReviewPublication
from app.database.models.pull_request import PullRequest
from app.database.models.repository import Repository
from app.database.models.review_run import ReviewRun
from app.database.session import async_engine, get_db_session
from app.main import app
from app.schemas.enums import (
    EvidenceType,
    FeedbackSource,
    FeedbackType,
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)


@pytest.fixture(autouse=True)
async def cleanup_database_engine() -> AsyncGenerator[None, None]:
    """Dispose engine connections between isolated test executions."""
    yield
    await async_engine.dispose()
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an asynchronous HTTP client configured with ASGITransport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def sample_dataset() -> AsyncGenerator[dict[str, uuid.UUID], None]:
    """Seed a representative review hierarchy for testing and cleanly tear it down."""
    async for session in get_db_session():
        unique_github_id = random.randint(1000000, 9999999)
        # 1. Repository
        repo = Repository(
            id=uuid.uuid4(),
            github_repo_id=unique_github_id,
            full_name=f"test-org/review-demo-{unique_github_id}",
            default_branch="main",
            is_active=True,
        )
        session.add(repo)
        await session.flush()

        # 2. Pull Request
        pr = PullRequest(
            id=uuid.uuid4(),
            repository_id=repo.id,
            pr_number=42,
            title="feat: secure payment flow",
            author="alice",
            base_sha="0000000000000000000000000000000000000001",
            head_sha="0000000000000000000000000000000000000002",
            state="open",
            additions=120,
            deletions=15,
            changed_files_count=3,
        )
        session.add(pr)
        await session.flush()

        # 3. Review Run
        run = ReviewRun(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            commit_sha="0000000000000000000000000000000000000002",
            status="COMPLETED",
            trigger_type="WEBHOOK",
            total_tokens=1500,
            total_cost_usd=0.035,
            latency_seconds=12.4,
            review_plan={
                "focus": "security",
                "specialists": ["security", "correctness"],
            },
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        # 4. Verified Finding
        finding_verified = Finding(
            id=uuid.uuid4(),
            review_run_id=run.id,
            agent_name="SecurityAgent",
            issue_type=IssueType.SECURITY.value,
            severity=Severity.HIGH.value,
            file_path="src/payment.py",
            line_number=45,
            side=FindingSide.RIGHT.value,
            title="SQL Injection Vulnerability",
            explanation="Raw string formatting in SQL query allows injection.",
            recommendation="Use parameterized query parameters.",
            confidence_score=0.95,
            raw_confidence=0.92,
            verification_status=VerificationStatus.VERIFIED.value,
            publish_status=PublishStatus.PUBLISHED.value,
            github_comment_id=11223344,
        )
        session.add(finding_verified)

        # 5. Rejected Finding
        finding_rejected = Finding(
            id=uuid.uuid4(),
            review_run_id=run.id,
            agent_name="StyleAgent",
            issue_type=IssueType.MAINTAINABILITY.value,
            severity=Severity.LOW.value,
            file_path="src/utils.py",
            line_number=10,
            side=FindingSide.RIGHT.value,
            title="Minor variable naming nitpick",
            explanation="Variable could be more descriptive.",
            recommendation="Rename x to counter.",
            confidence_score=0.40,
            raw_confidence=0.50,
            verification_status=VerificationStatus.REJECTED.value,
            rejection_reason="Low severity stylistic nitpick dropped by critic policy",
            publish_status=PublishStatus.UNPUBLISHED.value,
        )
        session.add(finding_rejected)
        await session.flush()

        # 6. Evidence Item attached to finding_verified
        evidence = EvidenceItem(
            id=uuid.uuid4(),
            review_run_id=run.id,
            finding_id=finding_verified.id,
            evidence_type=EvidenceType.STATIC_ANALYSIS.value,
            file_path="src/payment.py",
            start_line=44,
            end_line=46,
            content_snippet='cursor.execute(f"SELECT * FROM accounts WHERE id = {acc_id}")',
            rule_or_cve_id="bandit.B608",
            corroborating_tool="bandit",
        )
        session.add(evidence)

        # 7. Publication audit
        pub = ReviewPublication(
            id=uuid.uuid4(),
            review_run_id=run.id,
            finding_id=finding_verified.id,
            repository_id=repo.github_repo_id,
            pr_number=pr.pr_number,
            commit_sha=run.commit_sha,
            idempotency_key=f"{repo.github_repo_id}:{pr.pr_number}:{finding_verified.id}:{run.commit_sha}",
            github_comment_id=11223344,
            publication_status=PublishStatus.PUBLISHED.value,
            published_at=datetime.now(UTC),
        )
        session.add(pub)

        # 8. Feedback
        fb = ReviewFeedback(
            id=uuid.uuid4(),
            finding_id=finding_verified.id,
            review_run_id=run.id,
            repository_id=repo.github_repo_id,
            pr_number=pr.pr_number,
            github_comment_id=11223344,
            feedback_type=FeedbackType.REACTION_POSITIVE.value,
            feedback_source=FeedbackSource.GITHUB_WEBHOOK.value,
            reviewer_username="alice",
            comment_body=None,
            extra_metadata={"reaction_content": "+1"},
        )
        session.add(fb)
        await session.commit()

        dataset = {
            "repo_id": repo.id,
            "pr_id": pr.id,
            "run_id": run.id,
            "finding_verified_id": finding_verified.id,
            "finding_rejected_id": finding_rejected.id,
            "evidence_id": evidence.id,
            "pub_id": pub.id,
            "feedback_id": fb.id,
        }
        try:
            yield dataset
        finally:
            # Clean up test entity hierarchy safely
            await session.delete(repo)
            await session.commit()
        break


@pytest.mark.unit
async def test_get_dashboard_metrics(
    async_client: httpx.AsyncClient,
    sample_dataset: dict[str, uuid.UUID],
) -> None:
    """Verify GET /api/v1/dashboard/metrics returns calculated counts."""
    assert sample_dataset["repo_id"] is not None
    response = await async_client.get("/api/v1/dashboard/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_repositories"] >= 1
    assert data["total_pull_requests"] >= 1
    assert data["total_review_runs"] >= 1
    assert data["total_findings"] >= 2
    assert data["verified_findings"] >= 1
    assert data["rejected_findings"] >= 1
    assert data["published_findings"] >= 1
    assert data["total_feedback_events"] >= 1


@pytest.mark.unit
async def test_repositories_endpoints(
    async_client: httpx.AsyncClient,
    sample_dataset: dict[str, uuid.UUID],
) -> None:
    """Verify repository list, get by ID, and repository PRs."""
    repo_id = sample_dataset["repo_id"]

    # 1. List
    list_resp = await async_client.get("/api/v1/repositories")
    assert list_resp.status_code == 200
    repos = list_resp.json()
    assert len(repos) >= 1
    assert any(r["id"] == str(repo_id) for r in repos)

    # 2. Get single
    get_resp = await async_client.get(f"/api/v1/repositories/{repo_id}")
    assert get_resp.status_code == 200
    repo = get_resp.json()
    assert "test-org/review-demo" in repo["full_name"]
    assert repo["pull_requests_count"] >= 1

    # 3. Not found
    fake_id = uuid.uuid4()
    not_found_resp = await async_client.get(f"/api/v1/repositories/{fake_id}")
    assert not_found_resp.status_code == 404

    # 4. Repo PRs
    prs_resp = await async_client.get(f"/api/v1/repositories/{repo_id}/pull-requests")
    assert prs_resp.status_code == 200
    prs = prs_resp.json()
    assert len(prs) >= 1
    assert prs[0]["pr_number"] == 42


@pytest.mark.unit
async def test_pull_requests_endpoints(
    async_client: httpx.AsyncClient,
    sample_dataset: dict[str, uuid.UUID],
) -> None:
    """Verify PR list, get by ID, and PR reviews."""
    pr_id = sample_dataset["pr_id"]

    # 1. List with filter
    list_resp = await async_client.get(
        "/api/v1/pull-requests", params={"state": "open"}
    )
    assert list_resp.status_code == 200
    prs = list_resp.json()
    assert len(prs) >= 1
    assert any(p["id"] == str(pr_id) for p in prs)

    # 2. Get single
    get_resp = await async_client.get(f"/api/v1/pull-requests/{pr_id}")
    assert get_resp.status_code == 200
    pr = get_resp.json()
    assert pr["pr_number"] == 42
    assert pr["title"] == "feat: secure payment flow"
    assert pr["review_runs_count"] >= 1
    assert pr["latest_review_run_status"] == "COMPLETED"

    # 3. PR reviews
    rev_resp = await async_client.get(f"/api/v1/pull-requests/{pr_id}/reviews")
    assert rev_resp.status_code == 200
    runs = rev_resp.json()
    assert len(runs) >= 1
    assert runs[0]["commit_sha"] == "0000000000000000000000000000000000000002"

    # 4. Not found
    fake_id = uuid.uuid4()
    assert (
        await async_client.get(f"/api/v1/pull-requests/{fake_id}")
    ).status_code == 404
    assert (
        await async_client.get(f"/api/v1/pull-requests/{fake_id}/reviews")
    ).status_code == 404


@pytest.mark.unit
async def test_review_runs_endpoints(
    async_client: httpx.AsyncClient,
    sample_dataset: dict[str, uuid.UUID],
) -> None:
    """Verify ReviewRun list, detail, findings, evidence, and publications."""
    run_id = sample_dataset["run_id"]
    finding_id = sample_dataset["finding_verified_id"]

    # 1. List runs
    list_resp = await async_client.get(
        "/api/v1/reviews", params={"status": "COMPLETED"}
    )
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert any(r["id"] == str(run_id) for r in runs)

    # 2. Single run
    get_resp = await async_client.get(f"/api/v1/reviews/{run_id}")
    assert get_resp.status_code == 200
    run = get_resp.json()
    assert run["status"] == "COMPLETED"
    assert run["findings_count"] == 2
    assert run["verified_findings_count"] == 1
    assert run["published_findings_count"] == 1
    assert run["review_plan"]["focus"] == "security"

    # 3. Findings for run with filter
    findings_resp = await async_client.get(
        f"/api/v1/reviews/{run_id}/findings",
        params={"verification_status": "VERIFIED"},
    )
    assert findings_resp.status_code == 200
    findings = findings_resp.json()
    assert len(findings) == 1
    assert findings[0]["id"] == str(finding_id)
    assert findings[0]["verification_status"] == "VERIFIED"
    assert findings[0]["publish_status"] == "PUBLISHED"
    assert len(findings[0]["evidence"]) == 1

    # 4. Evidence for run
    evidence_resp = await async_client.get(f"/api/v1/reviews/{run_id}/evidence")
    assert evidence_resp.status_code == 200
    items = evidence_resp.json()
    assert len(items) >= 1
    assert items[0]["corroborating_tool"] == "bandit"

    # 5. Publications for run
    pubs_resp = await async_client.get(f"/api/v1/reviews/{run_id}/publications")
    assert pubs_resp.status_code == 200
    pubs = pubs_resp.json()
    assert len(pubs) == 1
    assert pubs[0]["github_comment_id"] == 11223344
    assert pubs[0]["status"] == "PUBLISHED"

    # 6. Feedback for run
    fb_resp = await async_client.get(f"/api/v1/reviews/{run_id}/feedback")
    assert fb_resp.status_code == 200
    fb_list = fb_resp.json()
    assert len(fb_list) == 1
    assert fb_list[0]["reviewer_username"] == "alice"


@pytest.mark.unit
async def test_findings_and_feedback_endpoints(
    async_client: httpx.AsyncClient,
    sample_dataset: dict[str, uuid.UUID],
) -> None:
    """Verify single finding detail, finding evidence, and feedback list/detail."""
    finding_id = sample_dataset["finding_verified_id"]
    feedback_id = sample_dataset["feedback_id"]

    # 1. Single finding
    f_resp = await async_client.get(f"/api/v1/findings/{finding_id}")
    assert f_resp.status_code == 200
    finding = f_resp.json()
    assert finding["title"] == "SQL Injection Vulnerability"
    assert finding["severity"] == "HIGH"
    assert finding["verification_status"] == "VERIFIED"

    # 2. Finding evidence
    ev_resp = await async_client.get(f"/api/v1/findings/{finding_id}/evidence")
    assert ev_resp.status_code == 200
    ev_list = ev_resp.json()
    assert len(ev_list) == 1
    assert ev_list[0]["rule_or_cve_id"] == "bandit.B608"

    # 2b. List all findings with query filters
    all_findings_resp = await async_client.get(
        "/api/v1/findings",
        params={"verification_status": "VERIFIED", "severity": "HIGH"},
    )
    assert all_findings_resp.status_code == 200
    matched_findings = all_findings_resp.json()
    assert len(matched_findings) >= 1
    assert all(f["verification_status"] == "VERIFIED" for f in matched_findings)
    assert all(f["severity"] == "HIGH" for f in matched_findings)

    # 3. Finding not found
    fake_id = uuid.uuid4()
    assert (await async_client.get(f"/api/v1/findings/{fake_id}")).status_code == 404
    assert (
        await async_client.get(f"/api/v1/findings/{fake_id}/evidence")
    ).status_code == 404

    # 4. List feedback
    fb_list_resp = await async_client.get("/api/v1/feedback", params={"pr_number": 42})
    assert fb_list_resp.status_code == 200
    feedbacks = fb_list_resp.json()
    assert len(feedbacks) >= 1

    # 5. Single feedback
    fb_get_resp = await async_client.get(f"/api/v1/feedback/{feedback_id}")
    assert fb_get_resp.status_code == 200
    fb = fb_get_resp.json()
    assert fb["feedback_type"] == "REACTION_POSITIVE"
    assert fb["reviewer_username"] == "alice"

    # 6. Feedback not found
    assert (await async_client.get(f"/api/v1/feedback/{fake_id}")).status_code == 404
