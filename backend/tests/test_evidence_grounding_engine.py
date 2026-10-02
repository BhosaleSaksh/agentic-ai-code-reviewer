"""Unit and integration tests for Evidence Grounding Engine services:

DiffEvidenceResolver, StaticEvidenceMatcher, FindingEvidenceValidator,
and EvidenceGroundingService.
"""

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
from app.schemas.verification import CriticStructuredOutput
from app.services.evidence.diff_resolver import DiffEvidenceResolver
from app.services.evidence.grounding_service import EvidenceGroundingService
from app.services.evidence.static_matcher import StaticEvidenceMatcher
from app.services.evidence.validator import FindingEvidenceValidator


@pytest.fixture
def sample_parsed_diff() -> ParsedDiff:
    """Fixture providing a multi-file unified diff with additions, deletions, and context."""
    hunk1 = DiffHunk(
        old_start=10,
        old_count=4,
        new_start=10,
        new_count=6,
        header="@@ -10,4 +10,6 @@",
        lines=[
            DiffLine(
                line_type=DiffLineType.CONTEXT,
                old_line_number=10,
                new_line_number=10,
                content="def login(username, password):",
                raw_line=" def login(username, password):",
            ),
            DiffLine(
                line_type=DiffLineType.DELETED,
                old_line_number=11,
                new_line_number=None,
                content="    raw_query = f'SELECT * FROM users WHERE u={username}'",
                raw_line="-    raw_query = f'SELECT * FROM users WHERE u={username}'",
            ),
            DiffLine(
                line_type=DiffLineType.ADDED,
                old_line_number=None,
                new_line_number=11,
                content="    # Sanitized query path",
                raw_line="+    # Sanitized query path",
            ),
            DiffLine(
                line_type=DiffLineType.ADDED,
                old_line_number=None,
                new_line_number=12,
                content="    query = db.select(User).where(User.name == username)",
                raw_line="+    query = db.select(User).where(User.name == username)",
            ),
            DiffLine(
                line_type=DiffLineType.ADDED,
                old_line_number=None,
                new_line_number=13,
                content="    return execute(query, password)",
                raw_line="+    return execute(query, password)",
            ),
            DiffLine(
                line_type=DiffLineType.CONTEXT,
                old_line_number=12,
                new_line_number=14,
                content="    return None",
                raw_line="     return None",
            ),
        ],
    )

    diff_file = DiffFile(
        old_path="backend/app/auth.py",
        new_path="backend/app/auth.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk1],
    )

    return ParsedDiff(files=[diff_file])


@pytest.fixture
def sample_candidate_finding() -> ReviewFinding:
    """Fixture providing a candidate ReviewFinding on line 12 of backend/app/auth.py."""
    return ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=12,
        side=FindingSide.RIGHT,
        title="SQL Parameterization Defect",
        explanation="The user input is passed directly to the query object without parameterization.",
        recommendation="Use bound parameters for user input.",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/auth.py",
                start_line=12,
                end_line=12,
                snippet="+    query = db.select(User).where(User.name == username)",
            )
        ],
        raw_confidence=0.85,
        verification_status=VerificationStatus.UNVERIFIED,
    )


# ==========================================
# 1. DiffEvidenceResolver Tests
# ==========================================


def test_diff_resolver_file_resolution(sample_parsed_diff: ParsedDiff) -> None:
    """Verify file resolution with exact, normalized, and windows-style paths."""
    resolver = DiffEvidenceResolver()

    # Exact match
    assert (
        resolver.file_exists_in_diff(sample_parsed_diff, "backend/app/auth.py") is True
    )
    # Windows-style backslashes
    assert (
        resolver.file_exists_in_diff(sample_parsed_diff, "backend\\app\\auth.py")
        is True
    )
    # Leading ./
    assert (
        resolver.file_exists_in_diff(sample_parsed_diff, "./backend/app/auth.py")
        is True
    )
    # Non-existent file
    assert (
        resolver.file_exists_in_diff(sample_parsed_diff, "backend/app/other.py")
        is False
    )
    # None diff handling
    assert resolver.file_exists_in_diff(None, "backend/app/auth.py") is False


def test_diff_resolver_line_coordinates(sample_parsed_diff: ParsedDiff) -> None:
    """Verify line coverage and changed-line detection on RIGHT and LEFT sides."""
    resolver = DiffEvidenceResolver()

    # Added line 12 is in diff and is changed
    assert (
        resolver.line_in_diff(
            sample_parsed_diff, "backend/app/auth.py", 12, FindingSide.RIGHT
        )
        is True
    )
    assert (
        resolver.is_changed_line(
            sample_parsed_diff, "backend/app/auth.py", 12, FindingSide.RIGHT
        )
        is True
    )

    # Context line 10 is in diff but NOT a changed line
    assert (
        resolver.line_in_diff(
            sample_parsed_diff, "backend/app/auth.py", 10, FindingSide.RIGHT
        )
        is True
    )
    assert (
        resolver.is_changed_line(
            sample_parsed_diff, "backend/app/auth.py", 10, FindingSide.RIGHT
        )
        is False
    )

    # Deleted line 11 on LEFT side
    assert (
        resolver.line_in_diff(
            sample_parsed_diff, "backend/app/auth.py", 11, FindingSide.LEFT
        )
        is True
    )
    assert (
        resolver.is_changed_line(
            sample_parsed_diff, "backend/app/auth.py", 11, FindingSide.LEFT
        )
        is True
    )

    # Line 99 is completely outside diff
    assert (
        resolver.line_in_diff(
            sample_parsed_diff, "backend/app/auth.py", 99, FindingSide.RIGHT
        )
        is False
    )
    assert (
        resolver.is_changed_line(
            sample_parsed_diff, "backend/app/auth.py", 99, FindingSide.RIGHT
        )
        is False
    )


def test_diff_resolver_excerpt_extraction(sample_parsed_diff: ParsedDiff) -> None:
    """Verify diff excerpt and surrounding code extraction around target line."""
    resolver = DiffEvidenceResolver()

    excerpt, header = resolver.extract_diff_excerpt(
        sample_parsed_diff, "backend/app/auth.py", 12, context_window=2
    )
    assert excerpt is not None
    assert header == "@@ -10,4 +10,6 @@"
    assert "query = db.select(User)" in excerpt

    surrounding = resolver.extract_surrounding_code(
        sample_parsed_diff, "backend/app/auth.py", 12, context_window=2
    )
    assert surrounding is not None
    assert (
        "12 |     query = db.select(User).where(User.name == username)" in surrounding
    )


# ==========================================
# 2. StaticEvidenceMatcher Tests
# ==========================================


def test_static_evidence_matcher_direct_and_proximate() -> None:
    """Verify static analysis evidence matching by coordinate proximity."""
    matcher = StaticEvidenceMatcher(line_proximity_window=3)

    finding = ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=20,
        title="Direct issue",
        explanation="Explanation",
        recommendation="Fix",
    )

    ev_direct = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=20,
        end_line=20,
        snippet="password = request.data['pwd']",
        corroborating_tool="semgrep",
        rule_or_cve_id="hardcoded-secret",
    )

    ev_proximate = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=22,
        end_line=22,
        snippet="other line",
        corroborating_tool="bandit",
        rule_or_cve_id="B105",
    )

    ev_unrelated = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=50,
        end_line=50,
        snippet="far away",
        corroborating_tool="bandit",
        rule_or_cve_id="B608",
    )

    matches = matcher.match_finding_evidence(
        finding, [ev_direct, ev_proximate, ev_unrelated]
    )
    assert len(matches) == 2

    direct_match = next(m for m in matches if m.rule_or_cve_id == "hardcoded-secret")
    assert direct_match.is_direct_match is True

    prox_match = next(m for m in matches if m.rule_or_cve_id == "B105")
    assert prox_match.is_direct_match is False


def test_static_evidence_matcher_extract_models() -> None:
    """Verify extraction of correlated EvidenceModel objects."""
    matcher = StaticEvidenceMatcher()
    finding = ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=10,
        title="Test finding",
        explanation="Exp",
        recommendation="Rec",
    )
    ev = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=10,
        end_line=10,
        snippet="token = 'abc'",
        rule_or_cve_id="B105",
        corroborating_tool="bandit",
    )

    models = matcher.extract_correlated_evidence_models(finding, [ev])
    assert len(models) == 1
    assert models[0].rule_or_cve_id == "B105"
    assert models[0].corroborating_tool == "bandit"


# ==========================================
# 3. FindingEvidenceValidator Deterministic Tests
# ==========================================


def test_validator_rejects_missing_file(
    sample_candidate_finding: ReviewFinding,
) -> None:
    """Verify rejection when cited file does not exist in changed files or diff."""
    validator = FindingEvidenceValidator()

    sample_candidate_finding.affected_file = "non_existent/file.py"
    is_valid, reason, result = validator.validate_candidate_finding(
        finding=sample_candidate_finding,
        parsed_diff=None,
        changed_files=["backend/app/auth.py"],
        commit_sha="a" * 40,
    )

    assert is_valid is False
    assert "does not exist in PR diff" in reason  # type: ignore[operator]
    assert result is not None
    assert result.verification_status == VerificationStatus.REJECTED
    assert result.confidence_score == 0.0


def test_validator_rejects_line_outside_diff(
    sample_candidate_finding: ReviewFinding, sample_parsed_diff: ParsedDiff
) -> None:
    """Verify rejection when cited line falls completely outside any modified diff hunk."""
    validator = FindingEvidenceValidator()

    sample_candidate_finding.line_number = 150  # Out of bounds
    is_valid, reason, result = validator.validate_candidate_finding(
        finding=sample_candidate_finding,
        parsed_diff=sample_parsed_diff,
        changed_files=["backend/app/auth.py"],
        commit_sha="a" * 40,
    )

    assert is_valid is False
    assert "falls outside all modified diff hunks" in reason  # type: ignore[operator]
    assert result is not None
    assert result.verification_status == VerificationStatus.REJECTED


def test_validator_rejects_commit_sha_mismatch(
    sample_candidate_finding: ReviewFinding,
) -> None:
    """Verify rejection when commit SHA does not match expected review commit."""
    validator = FindingEvidenceValidator()

    is_valid, reason, result = validator.validate_candidate_finding(
        finding=sample_candidate_finding,
        parsed_diff=None,
        changed_files=["backend/app/auth.py"],
        commit_sha="a" * 40,
        expected_commit_sha="b" * 40,
    )

    assert is_valid is False
    assert "Commit SHA mismatch" in reason  # type: ignore[operator]
    assert result is not None
    assert result.verification_status == VerificationStatus.REJECTED


def test_validator_rejects_invalid_line_number(
    sample_candidate_finding: ReviewFinding,
) -> None:
    """Verify rejection of non-positive line number."""
    validator = FindingEvidenceValidator()

    # Bypass pydantic validation for testing gate
    object.__setattr__(sample_candidate_finding, "line_number", 0)

    is_valid, reason, result = validator.validate_candidate_finding(
        finding=sample_candidate_finding,
        parsed_diff=None,
        changed_files=["backend/app/auth.py"],
        commit_sha="a" * 40,
    )

    assert is_valid is False
    assert "Invalid line number 0" in reason  # type: ignore[operator]


# ==========================================
# 4. EvidenceGroundingService Tests
# ==========================================


def test_grounding_service_context_preparation(
    sample_candidate_finding: ReviewFinding, sample_parsed_diff: ParsedDiff
) -> None:
    """Verify complete VerificationContext assembly with diff snippets and static evidence."""
    service = EvidenceGroundingService()

    static_ev = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=12,
        end_line=12,
        snippet="query = db.select(User)",
        rule_or_cve_id="B608",
        corroborating_tool="bandit",
    )

    can_proceed, rejection, context = service.prepare_verification_context(
        finding=sample_candidate_finding,
        parsed_diff=sample_parsed_diff,
        changed_files=["backend/app/auth.py"],
        review_run_id="run-ground-01",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
        evidence_items=[static_ev],
    )

    assert can_proceed is True
    assert rejection is None
    assert context.file_exists is True
    assert context.line_in_diff is True
    assert context.line_in_changed_hunk is True
    assert context.diff_snippet is not None
    assert len(context.correlated_static_evidence) == 1
    assert context.correlated_static_evidence[0].rule_or_cve_id == "B608"


def test_grounding_service_confidence_calibration(
    sample_candidate_finding: ReviewFinding, sample_parsed_diff: ParsedDiff
) -> None:
    """Verify that confidence calibration integrates deterministic diff and static signals."""
    service = EvidenceGroundingService(verification_confidence_threshold=0.70)

    static_ev = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=12,
        end_line=12,
        snippet="query = db.select(User)",
        rule_or_cve_id="B608",
        corroborating_tool="bandit",
    )

    _, _, context = service.prepare_verification_context(
        finding=sample_candidate_finding,
        parsed_diff=sample_parsed_diff,
        changed_files=["backend/app/auth.py"],
        review_run_id="run-ground-02",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
        evidence_items=[static_ev],
    )

    # 1. Strong verification with supporting static analysis and changed line
    llm_output_strong = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.85,
        evidence_sufficiency=True,
        contradiction_detected=False,
        critic_notes="Clear SQL injection pattern.",
        verification_reasons=["Direct SQL query interpolation."],
    )
    score_strong = service.calibrate_confidence(context, llm_output_strong)
    # 0.85 + 0.05 (changed line) + 0.10 (static evidence) = 1.00
    assert score_strong >= 0.95

    # 2. Contradicted verification drops score heavily
    llm_output_contradicted = CriticStructuredOutput(
        decision="REJECTED",
        calibrated_confidence=0.85,
        evidence_sufficiency=True,
        contradiction_detected=True,
        critic_notes="Query already uses ORM parameter binding.",
    )
    score_contra = service.calibrate_confidence(context, llm_output_contradicted)
    assert score_contra <= 0.50

    # 3. Decision synthesis marks status correctly
    decision_strong = service.synthesize_verification_decision(
        context, llm_output_strong
    )
    assert decision_strong.verification_status == VerificationStatus.VERIFIED
    assert decision_strong.is_verified is True
    assert len(decision_strong.verified_evidence) >= 1

    decision_contra = service.synthesize_verification_decision(
        context, llm_output_contradicted
    )
    assert decision_contra.verification_status == VerificationStatus.REJECTED
    assert decision_contra.is_rejected is True
    assert "Contradiction detected" in "; ".join(decision_contra.rejected_reasons)


def test_validator_rejects_malformed_fields(
    sample_candidate_finding: ReviewFinding, sample_parsed_diff: ParsedDiff
) -> None:
    """Verify validator rejects empty title, explanation, or affected_file."""
    validator = FindingEvidenceValidator()

    # Empty title
    f_title = sample_candidate_finding.model_copy(update={"title": "   "})
    ok, reason, res = validator.validate_candidate_finding(
        f_title, sample_parsed_diff, ["backend/app/auth.py"], "a" * 40
    )
    assert ok is False
    assert "empty title" in (reason or "")
    assert res is not None and res.is_rejected is True

    # Empty explanation
    f_expl = sample_candidate_finding.model_copy(update={"explanation": ""})
    ok, reason, res = validator.validate_candidate_finding(
        f_expl, sample_parsed_diff, ["backend/app/auth.py"], "a" * 40
    )
    assert ok is False
    assert "empty explanation" in (reason or "")
    assert res is not None and res.is_rejected is True

    # Empty affected_file
    f_file = sample_candidate_finding.model_copy(update={"affected_file": ""})
    ok, reason, res = validator.validate_candidate_finding(
        f_file, sample_parsed_diff, ["backend/app/auth.py"], "a" * 40
    )
    assert ok is False
    assert "empty affected_file" in (reason or "")
    assert res is not None and res.is_rejected is True


def test_diff_resolver_edge_cases(sample_parsed_diff: ParsedDiff) -> None:
    """Verify diff resolver handles None diff and out-of-hunk line queries."""
    resolver = DiffEvidenceResolver()

    assert resolver.resolve_file(None, "foo.py") is None
    assert resolver.file_exists_in_diff(None, "foo.py") is False
    assert resolver.line_in_diff(None, "foo.py", 10) is False
    assert resolver.get_covering_hunk(None, "foo.py", 10) is None

    # Line not in any hunk of existing file
    hunk = resolver.get_covering_hunk(sample_parsed_diff, "backend/app/auth.py", 999)
    assert hunk is None
    excerpt, header = resolver.extract_diff_excerpt(
        sample_parsed_diff, "backend/app/auth.py", 999
    )
    assert excerpt is None
    assert header is None


def test_static_matcher_edge_cases(sample_candidate_finding: ReviewFinding) -> None:
    """Verify static matcher handles empty items and dictionary formats."""
    matcher = StaticEvidenceMatcher()

    assert matcher.match_finding_evidence(sample_candidate_finding, None) == []
    assert matcher.match_finding_evidence(sample_candidate_finding, []) == []

    # Dictionary format
    raw_ev = {
        "evidence_type": "STATIC_ANALYSIS",
        "file_path": "backend/app/auth.py",
        "start_line": 12,
        "end_line": 12,
        "snippet": "code snippet",
        "rule_or_cve_id": "bandit.B608",
        "corroborating_tool": "bandit",
    }
    matched = matcher.match_finding_evidence(sample_candidate_finding, [raw_ev])
    assert len(matched) == 1
    assert matched[0].rule_or_cve_id == "bandit.B608"
