"""Tests for canonical Pydantic v2 schemas: ReviewFinding, EvidenceModel, ReviewPlan, and Diff models."""

import json
import uuid

import pytest
from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    EvidenceType,
    FileChangeType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan
from pydantic import ValidationError

# ==============================================================================
# EvidenceModel Tests
# ==============================================================================


def test_evidence_model_valid() -> None:
    """Test valid EvidenceModel creation and properties."""
    evidence = EvidenceModel(
        evidence_type=EvidenceType.DIFF_HUNK,
        file_path="backend/app/auth.py",
        start_line=10,
        end_line=15,
        snippet="def authenticate(user, password):",
        rule_or_cve_id="bandit.B105",
        corroborating_tool="bandit",
        metadata={"confidence": "HIGH"},
    )
    assert evidence.evidence_type == EvidenceType.DIFF_HUNK
    assert evidence.file_path == "backend/app/auth.py"
    assert evidence.start_line == 10
    assert evidence.end_line == 15
    assert evidence.snippet == "def authenticate(user, password):"
    assert evidence.rule_or_cve_id == "bandit.B105"
    assert evidence.corroborating_tool == "bandit"
    assert evidence.metadata == {"confidence": "HIGH"}


def test_evidence_model_alias_support() -> None:
    """Test EvidenceModel aliases (content_snippet and extra_metadata)."""
    evidence = EvidenceModel.model_validate(
        {
            "evidence_type": "STATIC_ANALYSIS",
            "file_path": "backend/app/main.py",
            "start_line": 20,
            "end_line": 20,
            "content_snippet": "app.add_middleware(...)",
            "extra_metadata": {"rule": "CWE-89"},
        }
    )
    assert evidence.snippet == "app.add_middleware(...)"
    assert evidence.metadata == {"rule": "CWE-89"}


def test_evidence_model_invalid_line_range() -> None:
    """Test EvidenceModel rejects end_line < start_line."""
    with pytest.raises(
        ValidationError, match="end_line .* cannot be less than start_line"
    ):
        EvidenceModel(
            evidence_type=EvidenceType.AST_CONTEXT,
            file_path="app.py",
            start_line=50,
            end_line=40,
            snippet="x = 1",
        )


def test_evidence_model_invalid_file_path() -> None:
    """Test EvidenceModel rejects blank file paths or null bytes."""
    with pytest.raises(
        ValidationError,
        match="file_path cannot be blank|String should have at least 1 character",
    ):
        EvidenceModel(
            evidence_type=EvidenceType.DEPENDENCY,
            file_path="   ",
            start_line=1,
            end_line=1,
            snippet="dep==1.0",
        )

    with pytest.raises(ValidationError, match="null bytes"):
        EvidenceModel(
            evidence_type=EvidenceType.DEPENDENCY,
            file_path="path/with/\x00/null",
            start_line=1,
            end_line=1,
            snippet="dep==1.0",
        )


def test_evidence_model_invalid_empty_snippet() -> None:
    """Test EvidenceModel rejects whitespace-only snippets."""
    with pytest.raises(
        ValidationError,
        match="snippet cannot be empty|String should have at least 1 character",
    ):
        EvidenceModel(
            evidence_type=EvidenceType.DIFF_HUNK,
            file_path="app.py",
            start_line=1,
            end_line=2,
            snippet="   \n\t  ",
        )


# ==============================================================================
# ReviewFinding Tests
# ==============================================================================


def test_review_finding_canonical_creation() -> None:
    """Test ReviewFinding creation matching Section J specification."""
    finding_id = uuid.uuid4()
    finding = ReviewFinding(
        finding_id=finding_id,
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=42,
        side=FindingSide.RIGHT,
        title="Hardcoded JWT Secret Detected",
        explanation="The JWT signing key is hardcoded directly in the module source.",
        recommendation="Extract the secret to an environment variable loaded via pydantic-settings.",
        confidence_score=0.87654,  # Should round to 3 decimals: 0.877
        suggested_patch="```suggestion\nsecret = settings.jwt_secret\n```",
        verification_status=VerificationStatus.VERIFIED,
        critic_notes="Corroborated by Semgrep rule python.jwt.hardcoded-secret.",
    )

    assert finding.finding_id == finding_id
    assert finding.issue_type == IssueType.SECURITY
    assert finding.severity == Severity.HIGH
    assert finding.affected_file == "backend/app/auth.py"
    assert finding.file_path == "backend/app/auth.py"
    assert finding.line_number == 42
    assert finding.side == FindingSide.RIGHT
    assert finding.title == "Hardcoded JWT Secret Detected"
    assert finding.confidence_score == 0.877
    assert finding.is_verified is True
    assert finding.is_suppressed is False
    assert finding.is_published is False


def test_review_finding_alias_and_serialization() -> None:
    """Test alias validation and model_dump / JSON serialization."""
    payload = {
        "id": "11111111-1111-1111-1111-111111111111",
        "issue_type": "BUG_LOGIC",
        "severity": "CRITICAL",
        "file_path": "services/order.py",
        "line_number": 88,
        "title": "Off-by-One in Pagination Slicing",
        "explanation": "List slice includes end index, causing duplicate items.",
        "recommendation": "Use exclusive upper bound.",
        "confidence_score": 0.95,
        "raw_confidence": 0.9234,
        "agent_name": "bug_logic_agent",
        "publish_status": "PUBLISHED",
        "github_comment_id": 987654321,
    }
    finding = ReviewFinding.model_validate(payload)
    assert finding.finding_id == uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert finding.affected_file == "services/order.py"
    assert finding.raw_confidence == 0.923
    assert finding.agent_name == "bug_logic_agent"
    assert finding.is_published is True

    # Test serialization
    dumped_dict = finding.model_dump()
    assert dumped_dict["issue_type"] == "BUG_LOGIC"
    assert dumped_dict["confidence_score"] == 0.95

    dumped_json = finding.model_dump_json()
    parsed_json = json.loads(dumped_json)
    assert parsed_json["affected_file"] == "services/order.py"
    assert parsed_json["publish_status"] == "PUBLISHED"


def test_review_finding_suppressed_state() -> None:
    """Test candidate finding suppressed by Critic."""
    finding = ReviewFinding(
        issue_type=IssueType.MAINTAINABILITY,
        severity=Severity.INFO,
        affected_file="utils.py",
        line_number=10,
        title="Unnecessary Variable Assignment",
        explanation="Variable assigned immediately before return.",
        recommendation="Inline the expression.",
        verification_status=VerificationStatus.SUPPRESSED_FALSE_POSITIVE,
        rejection_reason="Pure stylistic nitpick below signal threshold.",
        critic_notes="Suppressed per NFR-1 false positive policy.",
    )
    assert finding.is_verified is False
    assert finding.is_suppressed is True
    assert finding.rejection_reason == "Pure stylistic nitpick below signal threshold."


def test_review_finding_validation_errors() -> None:
    """Test validation errors for invalid fields."""
    # Line number < 1
    with pytest.raises(ValidationError, match="line_number"):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="main.py",
            line_number=0,
            title="Invalid Line",
            explanation="Explanation",
            recommendation="Recommendation",
        )

    # Confidence score > 1.0
    with pytest.raises(ValidationError, match="confidence_score"):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="main.py",
            line_number=1,
            confidence_score=1.5,
            title="Invalid Confidence",
            explanation="Explanation",
            recommendation="Recommendation",
        )

    # Empty title
    with pytest.raises(
        ValidationError, match="title|String should have at least 1 character"
    ):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="main.py",
            line_number=1,
            title="   ",
            explanation="Explanation",
            recommendation="Recommendation",
        )

    # Empty explanation
    with pytest.raises(
        ValidationError, match="explanation|String should have at least 1 character"
    ):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="main.py",
            line_number=1,
            title="Valid Title",
            explanation="   ",
            recommendation="Recommendation",
        )

    # Empty recommendation
    with pytest.raises(
        ValidationError, match="recommendation|String should have at least 1 character"
    ):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="main.py",
            line_number=1,
            title="Valid Title",
            explanation="Valid Explanation",
            recommendation="   ",
        )

    # Blank affected_file
    with pytest.raises(
        ValidationError,
        match="affected_file cannot be blank|String should have at least 1 character",
    ):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="   ",
            line_number=1,
            title="Valid Title",
            explanation="Valid Explanation",
            recommendation="Valid Recommendation",
        )

    # Null bytes in affected_file
    with pytest.raises(
        ValidationError, match="affected_file cannot contain null bytes"
    ):
        ReviewFinding(
            issue_type=IssueType.ERROR_HANDLING,
            severity=Severity.LOW,
            affected_file="path/with/\x00/null.py",
            line_number=1,
            title="Valid Title",
            explanation="Valid Explanation",
            recommendation="Valid Recommendation",
        )


# ==============================================================================
# ReviewPlan Tests
# ==============================================================================


def test_review_plan_valid() -> None:
    """Test valid ReviewPlan creation and field stripping."""
    plan = ReviewPlan(
        review_scope="focused",
        active_agents=[" security_agent ", "bug_logic_agent"],
        focus_areas=[" sql injection ", "input validation"],
        target_files=[" backend/app/auth.py ", "backend/app/db.py"],
        is_large_pr=True,
        chunking_strategy="FILE_MODULE",
        file_chunks=[["backend/app/auth.py"], ["backend/app/db.py"]],
        reasoning="Security-critical files modified; active agents prioritized.",
        metadata={"total_files": 2, "estimated_tokens": 1200},
    )

    assert plan.review_scope == "FOCUSED"
    assert plan.active_agents == ["security_agent", "bug_logic_agent"]
    assert plan.focus_areas == ["sql injection", "input validation"]
    assert plan.target_files == ["backend/app/auth.py", "backend/app/db.py"]
    assert plan.is_large_pr is True
    assert plan.chunking_strategy == "FILE_MODULE"
    assert len(plan.file_chunks) == 2
    assert plan.metadata["total_files"] == 2


def test_review_plan_serialization() -> None:
    """Test ReviewPlan JSON serialization and deserialization."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=[
            "security_agent",
            "bug_logic_agent",
            "error_handling_agent",
            "test_analysis_agent",
        ],
    )
    json_str = plan.model_dump_json()
    restored = ReviewPlan.model_validate_json(json_str)
    assert restored.review_scope == "FULL"
    assert len(restored.active_agents) == 4


def test_review_plan_invalid_blank_scope() -> None:
    """Test ReviewPlan rejects blank review_scope."""
    with pytest.raises(ValidationError, match="review_scope cannot be blank"):
        ReviewPlan(review_scope="   ")


# ==============================================================================
# Diff Schemas Tests
# ==============================================================================


def test_diff_line_and_hunk_querying() -> None:
    """Test DiffLine and DiffHunk query helper methods."""
    l1 = DiffLine(
        line_type=DiffLineType.CONTEXT,
        old_line_number=10,
        new_line_number=10,
        content="code",
    )
    l2 = DiffLine(
        line_type=DiffLineType.DELETED,
        old_line_number=11,
        new_line_number=None,
        content="old_code",
    )
    l3 = DiffLine(
        line_type=DiffLineType.ADDED,
        old_line_number=None,
        new_line_number=11,
        content="new_code",
    )

    hunk = DiffHunk(
        old_start=10,
        old_count=2,
        new_start=10,
        new_count=2,
        header="@@ -10,2 +10,2 @@",
        lines=[l1, l2, l3],
    )

    assert len(hunk.added_lines) == 1
    assert len(hunk.deleted_lines) == 1
    assert len(hunk.context_lines) == 1

    assert hunk.contains_line(10, FindingSide.RIGHT) is True
    assert hunk.contains_line(11, FindingSide.RIGHT) is True
    assert hunk.contains_line(12, FindingSide.RIGHT) is False

    assert hunk.contains_changed_line(11, FindingSide.RIGHT) is True
    assert (
        hunk.contains_changed_line(10, FindingSide.RIGHT) is False
    )  # Context, not changed
    assert hunk.contains_changed_line(11, FindingSide.LEFT) is True


def test_diff_file_and_parsed_diff_querying() -> None:
    """Test ParsedDiff file lookup and line verification."""
    hunk = DiffHunk(
        old_start=1,
        old_count=1,
        new_start=1,
        new_count=2,
        header="@@ -1 +1,2 @@",
        lines=[
            DiffLine(
                line_type=DiffLineType.CONTEXT,
                old_line_number=1,
                new_line_number=1,
                content="import os",
            ),
            DiffLine(
                line_type=DiffLineType.ADDED,
                old_line_number=None,
                new_line_number=2,
                content="import sys",
            ),
        ],
    )
    diff_file = DiffFile(
        old_path="main.py",
        new_path="main.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk],
    )
    parsed = ParsedDiff(files=[diff_file])

    assert parsed.total_files == 1
    assert parsed.total_additions == 1
    assert parsed.total_deletions == 0
    assert parsed.has_file("main.py") is True
    assert parsed.has_file("b/main.py") is True
    assert parsed.has_file("unknown.py") is False

    assert parsed.is_line_in_diff("main.py", 2, FindingSide.RIGHT) is True
    assert parsed.is_changed_line("main.py", 2, FindingSide.RIGHT) is True
    assert parsed.is_changed_line("main.py", 1, FindingSide.RIGHT) is False
