"""Tests for bidirectional mapping between ReviewFinding and SQLAlchemy ORM Finding."""

import uuid

import pytest
from app.database.models.finding import Finding
from app.database.models.pull_request import PullRequest
from app.database.models.repository import Repository
from app.database.models.review_run import ReviewRun
from app.database.session import get_db_session
from app.schemas.enums import (
    EvidenceType,
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.services.finding_mapper import (
    evidence_to_orm,
    finding_to_orm,
    orm_to_evidence,
    orm_to_finding,
)
from sqlalchemy import select


def test_evidence_mapping_round_trip() -> None:
    """Test EvidenceModel <-> EvidenceItem bidirectional conversion."""
    run_id = uuid.uuid4()
    finding_id = uuid.uuid4()

    original = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=15,
        end_line=25,
        snippet="token = jwt.decode(payload, verify=False)",
        rule_or_cve_id="bandit.B105",
        corroborating_tool="bandit",
        metadata={"confidence": "HIGH", "severity": "HIGH"},
    )

    orm_item = evidence_to_orm(
        evidence=original,
        review_run_id=run_id,
        finding_id=finding_id,
    )

    assert orm_item.review_run_id == run_id
    assert orm_item.finding_id == finding_id
    assert orm_item.evidence_type == "STATIC_ANALYSIS"
    assert orm_item.file_path == "backend/app/auth.py"
    assert orm_item.start_line == 15
    assert orm_item.end_line == 25
    assert orm_item.content_snippet == "token = jwt.decode(payload, verify=False)"
    assert orm_item.rule_or_cve_id == "bandit.B105"
    assert orm_item.corroborating_tool == "bandit"
    assert orm_item.extra_metadata == {"confidence": "HIGH", "severity": "HIGH"}

    restored = orm_to_evidence(orm_item)
    assert restored.evidence_type == original.evidence_type
    assert restored.file_path == original.file_path
    assert restored.start_line == original.start_line
    assert restored.end_line == original.end_line
    assert restored.snippet == original.snippet
    assert restored.rule_or_cve_id == original.rule_or_cve_id
    assert restored.corroborating_tool == original.corroborating_tool
    assert restored.metadata == original.metadata


def test_verified_finding_round_trip() -> None:
    """Test normal verified finding mapping preserves all fields."""
    run_id = uuid.uuid4()
    finding_id = uuid.uuid4()

    evidence = EvidenceModel(
        evidence_type=EvidenceType.DIFF_HUNK,
        file_path="services/payment.py",
        start_line=50,
        end_line=55,
        snippet="+ total = calculate_total(items)",
    )

    original = ReviewFinding(
        finding_id=finding_id,
        agent_name="bug_logic_agent",
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.HIGH,
        affected_file="services/payment.py",
        line_number=52,
        side=FindingSide.RIGHT,
        title="Missing Currency Conversion",
        explanation="calculate_total does not account for user currency preferences.",
        recommendation="Pass currency code to calculate_total.",
        suggested_patch="```suggestion\n+ total = calculate_total(items, currency=user.currency)\n```",
        confidence_score=0.895,
        raw_confidence=0.85,
        verification_status=VerificationStatus.VERIFIED,
        critic_notes="Line verified in active diff hunk; logic confirmed.",
        publish_status=PublishStatus.PUBLISHED,
        github_comment_id=123456789,
        evidence=[evidence],
    )

    orm = finding_to_orm(original, review_run_id=run_id)
    assert orm.id == finding_id
    assert orm.review_run_id == run_id
    assert orm.agent_name == "bug_logic_agent"
    assert orm.issue_type == "BUG_LOGIC"
    assert orm.severity == "HIGH"
    assert orm.file_path == "services/payment.py"
    assert orm.line_number == 52
    assert orm.side == "RIGHT"
    assert orm.confidence_score == 0.895
    assert orm.raw_confidence == 0.85
    assert orm.verification_status == "VERIFIED"
    assert orm.publish_status == "PUBLISHED"
    assert orm.github_comment_id == 123456789
    assert len(orm.evidence_items) == 1

    restored = orm_to_finding(orm)
    assert restored.finding_id == original.finding_id
    assert restored.agent_name == original.agent_name
    assert restored.issue_type == original.issue_type
    assert restored.severity == original.severity
    assert restored.affected_file == original.affected_file
    assert restored.line_number == original.line_number
    assert restored.side == original.side
    assert restored.title == original.title
    assert restored.explanation == original.explanation
    assert restored.recommendation == original.recommendation
    assert restored.suggested_patch == original.suggested_patch
    assert restored.confidence_score == original.confidence_score
    assert restored.raw_confidence == original.raw_confidence
    assert restored.verification_status == original.verification_status
    assert restored.critic_notes == original.critic_notes
    assert restored.publish_status == original.publish_status
    assert restored.github_comment_id == original.github_comment_id
    assert len(restored.evidence) == 1
    assert restored.evidence[0].file_path == "services/payment.py"


def test_candidate_finding_round_trip() -> None:
    """Test candidate unverified finding with raw confidence and no patch."""
    original = ReviewFinding(
        agent_name="security_agent",
        issue_type=IssueType.SECURITY,
        severity=Severity.CRITICAL,
        affected_file="api/routes.py",
        line_number=10,
        side=FindingSide.RIGHT,
        title="Potential SQL Injection",
        explanation="Raw SQL query concatenation with user input.",
        recommendation="Use parameterized queries via SQLAlchemy text bindparams.",
        confidence_score=0.0,
        raw_confidence=0.95,
        verification_status=VerificationStatus.UNVERIFIED,
        publish_status=PublishStatus.UNPUBLISHED,
    )

    orm = finding_to_orm(original)
    assert orm.verification_status == "UNVERIFIED"
    assert orm.confidence_score == 0.0
    assert orm.raw_confidence == 0.95
    assert orm.suggested_patch is None
    assert orm.critic_notes is None

    restored = orm_to_finding(orm)
    assert restored.is_verified is False
    assert restored.verification_status == VerificationStatus.UNVERIFIED
    assert restored.raw_confidence == 0.95
    assert restored.suggested_patch is None


def test_suppressed_finding_round_trip() -> None:
    """Test suppressed finding with rejection reason and critic notes."""
    original = ReviewFinding(
        issue_type=IssueType.TEST_ADEQUACY,
        severity=Severity.LOW,
        affected_file="tests/test_foo.py",
        line_number=20,
        side=FindingSide.RIGHT,
        title="Missing Edge Case Test",
        explanation="No test for negative integers.",
        recommendation="Add parameterized negative test.",
        confidence_score=0.45,
        verification_status=VerificationStatus.SUPPRESSED_FALSE_POSITIVE,
        rejection_reason="Test exists in adjacent test file; false alarm.",
        critic_notes="Critic verified existing test coverage in test_foo_edge.py.",
    )

    orm = finding_to_orm(original)
    assert orm.verification_status == "SUPPRESSED_FALSE_POSITIVE"
    assert orm.rejection_reason == "Test exists in adjacent test file; false alarm."

    restored = orm_to_finding(orm)
    assert restored.is_suppressed is True
    assert restored.verification_status == VerificationStatus.SUPPRESSED_FALSE_POSITIVE
    assert restored.rejection_reason == original.rejection_reason
    assert restored.critic_notes == original.critic_notes


@pytest.mark.asyncio
async def test_database_persistence_of_mapped_finding() -> None:
    """Integration test: Persist mapped ReviewFinding into PostgreSQL and read back."""
    async for session in get_db_session():
        # Create hierarchy: Repository -> PullRequest -> ReviewRun
        repo = Repository(
            full_name=f"test-owner/test-repo-{uuid.uuid4().hex[:6]}",
            github_repo_id=abs(hash(uuid.uuid4())) % 10000000,
            default_branch="main",
            is_active=True,
        )
        session.add(repo)
        await session.flush()

        pr = PullRequest(
            repository_id=repo.id,
            pr_number=abs(hash(uuid.uuid4())) % 10000,
            title="Add authentication module",
            base_sha="0000000000000000000000000000000000000001",
            head_sha="0000000000000000000000000000000000000002",
            author="dev",
            state="open",
        )
        session.add(pr)
        await session.flush()

        run = ReviewRun(
            pull_request_id=pr.id,
            commit_sha=pr.head_sha,
            status="completed",
        )
        session.add(run)
        await session.flush()

        # Create Pydantic ReviewFinding with Evidence
        finding_id = uuid.uuid4()
        finding = ReviewFinding(
            finding_id=finding_id,
            agent_name="security_agent",
            issue_type=IssueType.SECURITY,
            severity=Severity.HIGH,
            affected_file="backend/app/auth.py",
            line_number=35,
            side=FindingSide.RIGHT,
            title="Weak Password Hashing Scheme",
            explanation="MD5 hash used instead of bcrypt or argon2.",
            recommendation="Use argon2-cffi for password hashing.",
            suggested_patch="```suggestion\nhash = argon2.hash(password)\n```",
            confidence_score=0.92,
            verification_status=VerificationStatus.VERIFIED,
            publish_status=PublishStatus.PUBLISHED,
            github_comment_id=555666777,
            evidence=[
                EvidenceModel(
                    evidence_type=EvidenceType.STATIC_ANALYSIS,
                    file_path="backend/app/auth.py",
                    start_line=34,
                    end_line=36,
                    snippet="hashlib.md5(password.encode()).hexdigest()",
                    rule_or_cve_id="bandit.B303",
                    corroborating_tool="bandit",
                )
            ],
        )

        # Map to ORM and persist
        orm_finding = finding_to_orm(finding, review_run_id=run.id)
        session.add(orm_finding)
        await session.commit()

        # Query back from PostgreSQL
        stmt = select(Finding).where(Finding.id == finding_id)
        result = await session.execute(stmt)
        queried = result.scalar_one()

        # Map back to ReviewFinding
        restored = orm_to_finding(queried)
        assert restored.finding_id == finding_id
        assert restored.title == "Weak Password Hashing Scheme"
        assert restored.severity == Severity.HIGH
        assert restored.affected_file == "backend/app/auth.py"
        assert restored.line_number == 35
        assert restored.side == FindingSide.RIGHT
        assert restored.confidence_score == 0.92
        assert restored.verification_status == VerificationStatus.VERIFIED
        assert restored.publish_status == PublishStatus.PUBLISHED
        assert restored.github_comment_id == 555666777
        assert len(restored.evidence) == 1
        assert (
            restored.evidence[0].snippet == "hashlib.md5(password.encode()).hexdigest()"
        )
        assert restored.evidence[0].rule_or_cve_id == "bandit.B303"
