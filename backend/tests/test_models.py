"""Unit and integration tests for SQLAlchemy domain models and database constraints."""

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from app.database.models import (
    Base,
    EvidenceItem,
    Finding,
    PullRequest,
    Repository,
    ReviewRun,
)
from app.database.session import async_engine, get_db_session
from sqlalchemy import Table, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapper, selectinload


@pytest.fixture(autouse=True)
async def cleanup_database_engine() -> AsyncGenerator[None, None]:
    """Dispose engine connections between isolated test event loops."""
    yield
    await async_engine.dispose()


def test_metadata_contains_all_five_models() -> None:
    """Verify that Base.metadata has registered all 5 domain models."""
    expected_tables = {
        "repositories",
        "pull_requests",
        "review_runs",
        "evidence_items",
        "findings",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())


def test_model_table_names_and_primary_keys() -> None:
    """Verify table names and primary key configuration for all models."""
    assert Repository.__tablename__ == "repositories"
    assert PullRequest.__tablename__ == "pull_requests"
    assert ReviewRun.__tablename__ == "review_runs"
    assert EvidenceItem.__tablename__ == "evidence_items"
    assert Finding.__tablename__ == "findings"

    for model in (Repository, PullRequest, ReviewRun, EvidenceItem, Finding):
        mapper = inspect(model)
        assert isinstance(mapper, Mapper)
        assert len(mapper.primary_key) == 1
        assert mapper.primary_key[0].name == "id"


def test_foreign_keys_configuration() -> None:
    """Verify expected foreign key constraints are declared on child models."""
    pr_table = PullRequest.__table__
    rr_table = ReviewRun.__table__
    finding_table = Finding.__table__
    evidence_table = EvidenceItem.__table__
    assert isinstance(pr_table, Table)
    assert isinstance(rr_table, Table)
    assert isinstance(finding_table, Table)
    assert isinstance(evidence_table, Table)

    pr_fks = {fk.target_fullname for fk in pr_table.foreign_keys}
    assert "repositories.id" in pr_fks

    rr_fks = {fk.target_fullname for fk in rr_table.foreign_keys}
    assert "pull_requests.id" in rr_fks

    finding_fks = {fk.target_fullname for fk in finding_table.foreign_keys}
    assert "review_runs.id" in finding_fks

    evidence_fks = {fk.target_fullname for fk in evidence_table.foreign_keys}
    assert "review_runs.id" in evidence_fks
    assert "findings.id" in evidence_fks


def test_unique_constraints_and_indexes() -> None:
    """Verify unique constraints and query indexes exist in table metadata."""
    pr_table = PullRequest.__table__
    rr_table = ReviewRun.__table__
    finding_table = Finding.__table__
    evidence_table = EvidenceItem.__table__
    assert isinstance(pr_table, Table)
    assert isinstance(rr_table, Table)
    assert isinstance(finding_table, Table)
    assert isinstance(evidence_table, Table)

    # PullRequest unique constraint
    pr_uq_names = {uq.name for uq in pr_table.constraints if hasattr(uq, "name")}
    assert "uq_pull_requests_repo_pr_number" in pr_uq_names

    # ReviewRun unique constraint and status index
    rr_uq_names = {uq.name for uq in rr_table.constraints if hasattr(uq, "name")}
    assert "uq_review_runs_pr_commit" in rr_uq_names

    rr_idx_names = {idx.name for idx in rr_table.indexes}
    assert "idx_review_runs_pr_status" in rr_idx_names

    # Finding indexes
    finding_idx_names = {idx.name for idx in finding_table.indexes}
    assert "idx_findings_run_status" in finding_idx_names
    assert "idx_findings_run_file" in finding_idx_names

    # EvidenceItem indexes
    evidence_idx_names = {idx.name for idx in evidence_table.indexes}
    assert "idx_evidence_items_run_file" in evidence_idx_names


def test_model_instantiation() -> None:
    """Verify domain models can be instantiated with valid attributes."""
    repo = Repository(
        github_repo_id=123456,
        full_name="owner/repo",
        default_branch="main",
        is_active=True,
    )
    assert repo.full_name == "owner/repo"
    assert repo.default_branch == "main"
    assert repo.is_active is True

    pr = PullRequest(
        repository_id=repo.id,
        pr_number=42,
        title="Fix authentication bug",
        author="alice",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="open",
        additions=10,
        deletions=2,
        changed_files_count=1,
    )
    assert pr.pr_number == 42
    assert pr.state == "open"
    assert pr.additions == 10
    assert pr.deletions == 2
    assert pr.changed_files_count == 1

    run = ReviewRun(
        pull_request_id=pr.id,
        commit_sha="b" * 40,
        status="QUEUED",
        trigger_type="WEBHOOK",
        total_tokens=0,
        total_cost_usd=Decimal("0.0000"),
    )
    assert run.status == "QUEUED"
    assert run.total_tokens == 0
    assert run.total_cost_usd == Decimal("0.0000")

    finding = Finding(
        review_run_id=run.id,
        issue_type="SECURITY",
        severity="HIGH",
        file_path="app/auth.py",
        line_number=10,
        side="RIGHT",
        title="Hardcoded secret detected",
        explanation="Secret key is written in plaintext.",
        recommendation="Store secret in environment variable.",
        confidence_score=0.95,
        verification_status="UNVERIFIED",
        publish_status="UNPUBLISHED",
    )
    assert finding.verification_status == "UNVERIFIED"
    assert finding.confidence_score == 0.95
    assert finding.publish_status == "UNPUBLISHED"

    evidence = EvidenceItem(
        review_run_id=run.id,
        finding_id=finding.id,
        evidence_type="STATIC_ANALYSIS",
        file_path="app/auth.py",
        start_line=10,
        end_line=12,
        content_snippet="SECRET_KEY = '12345'",
        rule_or_cve_id="bandit.B105",
        corroborating_tool="bandit",
    )
    assert evidence.evidence_type == "STATIC_ANALYSIS"
    assert repr(repo).startswith("<Repository")
    assert repr(pr).startswith("<PullRequest")
    assert repr(run).startswith("<ReviewRun")
    assert repr(finding).startswith("<Finding")
    assert repr(evidence).startswith("<EvidenceItem")


@pytest.mark.integration
async def test_database_server_defaults_applied() -> None:
    """Verify database applies server_defaults when fields are omitted."""
    async for session in get_db_session():
        repo = Repository(
            github_repo_id=888001,
            full_name="default-org/default-repo",
        )
        session.add(repo)
        await session.flush()
        await session.refresh(repo)

        assert repo.is_active is True
        assert repo.default_branch == "main"
        assert repo.created_at is not None
        assert repo.updated_at is not None

        pr = PullRequest(
            repository_id=repo.id,
            pr_number=1,
            title="Initial PR",
            author="dev",
            base_sha="0" * 40,
            head_sha="1" * 40,
        )
        session.add(pr)
        await session.flush()
        await session.refresh(pr)

        assert pr.state == "open"
        assert pr.additions == 0
        assert pr.deletions == 0
        assert pr.changed_files_count == 0

        run = ReviewRun(
            pull_request_id=pr.id,
            commit_sha="1" * 40,
        )
        session.add(run)
        await session.flush()
        await session.refresh(run)

        assert run.status == "QUEUED"
        assert run.trigger_type == "WEBHOOK"
        assert run.total_tokens == 0
        assert run.total_cost_usd == Decimal("0.0000")

        await session.delete(repo)
        await session.flush()


@pytest.mark.integration
async def test_database_persistence_and_relationships() -> None:
    """Verify persistence of full domain hierarchy and relationship traversal."""
    async for session in get_db_session():
        # Clean test entity hierarchy
        repo = Repository(
            github_repo_id=999001,
            full_name="test-org/test-repo",
            default_branch="main",
            is_active=True,
        )
        session.add(repo)
        await session.flush()

        pr = PullRequest(
            repository_id=repo.id,
            pr_number=101,
            title="Add OAuth2 Provider",
            author="contributor",
            base_sha="1111111111111111111111111111111111111111",
            head_sha="2222222222222222222222222222222222222222",
            state="open",
            additions=50,
            deletions=10,
            changed_files_count=3,
        )
        session.add(pr)
        await session.flush()

        run = ReviewRun(
            pull_request_id=pr.id,
            commit_sha="2222222222222222222222222222222222222222",
            status="IN_PROGRESS",
            trigger_type="WEBHOOK",
            total_tokens=1500,
            total_cost_usd=Decimal("0.0450"),
            latency_seconds=Decimal("12.50"),
            review_plan={"active_agents": ["security", "bug_logic"]},
        )
        session.add(run)
        await session.flush()

        finding = Finding(
            review_run_id=run.id,
            agent_name="security_agent",
            issue_type="SECURITY",
            severity="HIGH",
            file_path="src/auth.py",
            line_number=25,
            side="RIGHT",
            title="Insecure password hash algorithm",
            explanation="MD5 is cryptographically broken.",
            recommendation="Use bcrypt or argon2.",
            suggested_patch="```suggestion\nhash = bcrypt.hash(pwd)\n```",
            confidence_score=0.92,
            verification_status="VERIFIED",
        )
        session.add(finding)
        await session.flush()

        evidence = EvidenceItem(
            review_run_id=run.id,
            finding_id=finding.id,
            evidence_type="STATIC_ANALYSIS",
            file_path="src/auth.py",
            start_line=25,
            end_line=26,
            content_snippet="hashlib.md5(password)",
            rule_or_cve_id="bandit.B303",
            corroborating_tool="bandit",
            extra_metadata={"cwe": "CWE-327"},
        )
        session.add(evidence)
        await session.flush()

        # Query back and verify hierarchy with eager loading
        stmt = (
            select(Repository)
            .where(Repository.id == repo.id)
            .options(
                selectinload(Repository.pull_requests)
                .selectinload(PullRequest.review_runs)
                .selectinload(ReviewRun.findings),
                selectinload(Repository.pull_requests)
                .selectinload(PullRequest.review_runs)
                .selectinload(ReviewRun.evidence_items),
            )
        )
        result = await session.execute(stmt)
        queried_repo = result.scalar_one()

        assert queried_repo.full_name == "test-org/test-repo"
        assert len(queried_repo.pull_requests) == 1

        queried_pr = queried_repo.pull_requests[0]
        assert queried_pr.pr_number == 101
        assert len(queried_pr.review_runs) == 1

        queried_run = queried_pr.review_runs[0]
        assert queried_run.commit_sha == "2222222222222222222222222222222222222222"
        assert len(queried_run.findings) == 1
        assert len(queried_run.evidence_items) == 1

        # Delete repository and verify cascade deletion across all child records
        await session.delete(queried_repo)
        await session.flush()

        # Confirm all children are gone
        pr_check = await session.execute(
            select(PullRequest).where(PullRequest.id == pr.id)
        )
        assert pr_check.scalar_one_or_none() is None

        run_check = await session.execute(
            select(ReviewRun).where(ReviewRun.id == run.id)
        )
        assert run_check.scalar_one_or_none() is None

        finding_check = await session.execute(
            select(Finding).where(Finding.id == finding.id)
        )
        assert finding_check.scalar_one_or_none() is None

        evidence_check = await session.execute(
            select(EvidenceItem).where(EvidenceItem.id == evidence.id)
        )
        assert evidence_check.scalar_one_or_none() is None


@pytest.mark.integration
async def test_pull_request_uniqueness_constraint() -> None:
    """Verify that duplicate (repository_id, pr_number) violates unique constraint."""
    async for session in get_db_session():
        repo = Repository(
            github_repo_id=999002,
            full_name="test-org/dup-repo",
            default_branch="main",
        )
        session.add(repo)
        await session.flush()

        pr1 = PullRequest(
            repository_id=repo.id,
            pr_number=5,
            title="First PR",
            author="alice",
            base_sha="a" * 40,
            head_sha="b" * 40,
        )
        session.add(pr1)
        await session.flush()

        pr2 = PullRequest(
            repository_id=repo.id,
            pr_number=5,  # Duplicate PR number for the same repository
            title="Duplicate PR",
            author="bob",
            base_sha="c" * 40,
            head_sha="d" * 40,
        )
        session.add(pr2)

        with pytest.raises(IntegrityError):
            await session.flush()

        # Clean up by rollback
        await session.rollback()

        # Clean up repo if needed
        clean_repo = await session.get(Repository, repo.id)
        if clean_repo:
            await session.delete(clean_repo)
            await session.flush()


@pytest.mark.integration
async def test_foreign_key_violation_raises_integrity_error() -> None:
    """Verify that referencing a non-existent parent raises IntegrityError."""
    async for session in get_db_session():
        orphan_pr = PullRequest(
            repository_id=uuid.uuid4(),  # Non-existent repository ID
            pr_number=999,
            title="Orphan PR",
            author="ghost",
            base_sha="a" * 40,
            head_sha="b" * 40,
        )
        session.add(orphan_pr)

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()
