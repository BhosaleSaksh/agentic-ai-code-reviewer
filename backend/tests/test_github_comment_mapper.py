"""Unit tests for GitHub review comment mapping and summary generation."""

import uuid

from app.schemas.enums import (
    EvidenceType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.services.github.comment_mapper import (
    _format_suggestion_block,
    format_finding_comment,
    map_finding_to_comment_payload,
)
from app.services.github.summary_generator import generate_review_summary


def test_format_finding_comment_structure() -> None:
    """Verify that comment contains distinct Issue, Evidence, and Recommendation sections."""
    finding = ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.SECURITY,
        severity=Severity.CRITICAL,
        affected_file="backend/app/auth.py",
        line_number=42,
        side=FindingSide.RIGHT,
        title="SQL Injection Vulnerability",
        explanation="Untrusted user input interpolated into SQL query.",
        recommendation="Use parameterized query with text(:user_id).",
        suggested_patch="stmt = select(User).where(User.id == user_id)",
        verification_status=VerificationStatus.VERIFIED,
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.STATIC_ANALYSIS,
                file_path="backend/app/auth.py",
                start_line=40,
                end_line=45,
                snippet="cursor.execute(f'SELECT * FROM users WHERE id={user_id}')",
                rule_or_cve_id="bandit.B608",
                corroborating_tool="bandit",
            )
        ],
    )

    body = format_finding_comment(finding)

    assert "### 🚨 **CRITICAL** — SQL Injection Vulnerability" in body
    assert "**Category:** `SECURITY`" in body
    assert "#### Issue" in body
    assert "Untrusted user input interpolated into SQL query." in body
    assert "#### Evidence" in body
    assert "Static Analysis (bandit) [bandit.B608]" in body
    assert "`backend/app/auth.py:40-45`" in body
    assert "#### Recommendation" in body
    assert "Use parameterized query with text(:user_id)." in body
    assert "#### Suggested Fix" in body
    assert "```suggestion\nstmt = select(User).where(User.id == user_id)\n```" in body


def test_format_finding_comment_no_leakage() -> None:
    """Ensure internal reasoning, critic notes, agent names, and raw confidence are omitted."""
    secret_note = "INTERNAL_CHAIN_OF_THOUGHT_SUPER_SECRET_REASONING_12345"
    agent_name = "SPECIALIST_SECURITY_AGENT_V2"

    finding = ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.HIGH,
        affected_file="backend/app/logic.py",
        line_number=10,
        side=FindingSide.RIGHT,
        title="Off-by-one index access",
        explanation="Loop accesses length without checking bounds.",
        recommendation="Use enumerate or range(len - 1).",
        verification_status=VerificationStatus.VERIFIED,
        critic_notes=secret_note,
        agent_name=agent_name,
        raw_confidence=0.95,
        confidence_score=0.98,
    )

    body = format_finding_comment(finding)

    assert secret_note not in body
    assert agent_name not in body
    assert "0.95" not in body
    assert "0.98" not in body
    assert "critic" not in body.lower()


def test_format_suggestion_block_variants() -> None:
    """Test suggestion block formatting with plain code, already fenced code, and suggestion fenced code."""
    # Plain code
    plain = "x = 42"
    assert _format_suggestion_block(plain) == "```suggestion\nx = 42\n```"

    # Already suggestion fenced
    already_sugg = "```suggestion\nx = 42\n```"
    assert _format_suggestion_block(already_sugg) == already_sugg

    # Generic backtick fenced
    generic_fenced = "```python\nx = 42\n```"
    assert _format_suggestion_block(generic_fenced) == "```suggestion\nx = 42\n```"


def test_map_finding_to_comment_payload() -> None:
    """Verify mapping from ReviewFinding to GitHubCommentPayload contract."""
    finding = ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.ERROR_HANDLING,
        severity=Severity.MEDIUM,
        affected_file="backend/app/service.py",
        line_number=88,
        side=FindingSide.LEFT,
        title="Uncaught network timeout",
        explanation="Missing try/except around HTTP client call.",
        recommendation="Wrap call in try/except TimeoutException.",
        verification_status=VerificationStatus.VERIFIED,
    )

    payload = map_finding_to_comment_payload(finding)

    assert payload.path == "backend/app/service.py"
    assert payload.line == 88
    assert payload.side == FindingSide.LEFT
    assert "Uncaught network timeout" in payload.body


def test_generate_review_summary_no_findings() -> None:
    """Verify summary output when there are zero verified findings."""
    summary = generate_review_summary(
        total_findings=5,
        verified_findings=[],
        rejected_count=5,
        commit_sha="a" * 40,
    )

    assert "## 🤖 Automated Code Review Summary" in summary
    assert "Target Commit:" in summary
    assert "No verified issues found" in summary
    assert "| Candidate Findings Analyzed | 5 |" in summary
    assert "| Verified Findings | **0** |" in summary
    assert "| Rejected / Suppressed Findings | 5 |" in summary


def test_generate_review_summary_with_findings_and_unanchored() -> None:
    """Verify summary breakdown by severity, issue category, and unanchored findings."""
    f1 = ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.SECURITY,
        severity=Severity.CRITICAL,
        affected_file="src/auth.py",
        line_number=20,
        title="Critical auth bypass",
        explanation="Auth check is bypassed if header is missing.",
        recommendation="Enforce auth check strictly.",
        verification_status=VerificationStatus.VERIFIED,
    )
    f2 = ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.HIGH,
        affected_file="src/math_utils.py",
        line_number=100,
        title="Zero division error",
        explanation="Denominator can be zero.",
        recommendation="Check denominator > 0.",
        verification_status=VerificationStatus.VERIFIED,
    )

    summary = generate_review_summary(
        total_findings=3,
        verified_findings=[f1, f2],
        rejected_count=1,
        unanchored_findings=[f2],
        commit_sha="b" * 40,
    )

    assert "Found **2** verified finding(s)" in summary
    assert "| 🚨 Critical | 1 |" in summary
    assert "| ⚠️ High | 1 |" in summary
    assert "| `SECURITY` | 1 |" in summary
    assert "| `BUG_LOGIC` | 1 |" in summary
    assert "### 📌 Additional Findings (Outside Changed Lines)" in summary
    assert "Zero division error" in summary
    assert "src/math_utils.py:100" in summary


def test_generate_review_summary_deterministic() -> None:
    """Verify summary generation is deterministic across multiple calls with same inputs."""
    finding = ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.TEST_ADEQUACY,
        severity=Severity.LOW,
        affected_file="tests/test_foo.py",
        line_number=15,
        title="Missing assertion",
        explanation="Test function does not call assert.",
        recommendation="Add assert statement.",
        verification_status=VerificationStatus.VERIFIED,
    )

    s1 = generate_review_summary(
        total_findings=1,
        verified_findings=[finding],
        rejected_count=0,
        commit_sha="c" * 40,
    )
    s2 = generate_review_summary(
        total_findings=1,
        verified_findings=[finding],
        rejected_count=0,
        commit_sha="c" * 40,
    )

    assert s1 == s2
