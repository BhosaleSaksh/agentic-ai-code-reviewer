"""Unit tests for publication eligibility and diff positioning validation."""

import uuid

import pytest
from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    FileChangeType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.finding import ReviewFinding
from app.services.github.eligibility import (
    FindingEligibilityValidator,
    PositioningValidator,
)
from app.services.github.errors import PublishValidationError


def make_finding(
    status: VerificationStatus, file_path: str = "src/app.py", line: int = 10
) -> ReviewFinding:
    return ReviewFinding(
        id=uuid.uuid4(),
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.HIGH,
        affected_file=file_path,
        line_number=line,
        side=FindingSide.RIGHT,
        title="Sample issue",
        explanation="Sample explanation",
        recommendation="Sample recommendation",
        verification_status=status,
    )


def test_verified_finding_is_eligible() -> None:
    finding = make_finding(VerificationStatus.VERIFIED)
    assert FindingEligibilityValidator.is_eligible(finding) is True
    # validate should not raise
    FindingEligibilityValidator.validate(finding)


@pytest.mark.parametrize(
    "ineligible_status",
    [
        VerificationStatus.UNVERIFIED,
        VerificationStatus.REJECTED,
        VerificationStatus.SUPPRESSED_FALSE_POSITIVE,
        VerificationStatus.DROPPED_LOW_CONFIDENCE,
    ],
)
def test_ineligible_statuses_rejected(ineligible_status: VerificationStatus) -> None:
    finding = make_finding(ineligible_status)
    assert FindingEligibilityValidator.is_eligible(finding) is False
    with pytest.raises(PublishValidationError) as exc_info:
        FindingEligibilityValidator.validate(finding)
    assert "is ineligible for GitHub publication" in str(exc_info.value)
    assert str(ineligible_status) in str(exc_info.value)


def test_partition_findings() -> None:
    f_verified = make_finding(VerificationStatus.VERIFIED)
    f_unverified = make_finding(VerificationStatus.UNVERIFIED)
    f_rejected = make_finding(VerificationStatus.REJECTED)
    f_suppressed = make_finding(VerificationStatus.SUPPRESSED_FALSE_POSITIVE)

    eligible, ineligible = FindingEligibilityValidator.partition_findings(
        [f_verified, f_unverified, f_rejected, f_suppressed]
    )

    assert len(eligible) == 1
    assert eligible[0].finding_id == f_verified.finding_id
    assert len(ineligible) == 3


@pytest.fixture
def sample_parsed_diff() -> ParsedDiff:
    """Fixture providing a unified diff covering src/app.py lines 10 to 15."""
    hunk = DiffHunk(
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
                content="def compute():",
            ),
            DiffLine(
                line_type=DiffLineType.DELETED,
                old_line_number=11,
                new_line_number=None,
                content="    return False",
            ),
            DiffLine(
                line_type=DiffLineType.ADDED,
                old_line_number=None,
                new_line_number=11,
                content="    val = calculate()",
            ),
            DiffLine(
                line_type=DiffLineType.ADDED,
                old_line_number=None,
                new_line_number=12,
                content="    return val",
            ),
            DiffLine(
                line_type=DiffLineType.CONTEXT,
                old_line_number=12,
                new_line_number=13,
                content="def main():",
            ),
        ],
    )
    diff_file = DiffFile(
        old_path="src/app.py",
        new_path="src/app.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk],
    )
    return ParsedDiff(files=[diff_file])


def test_positioning_validator_in_diff_hunk(sample_parsed_diff: ParsedDiff) -> None:
    # Line 11 is an added line on RIGHT side
    finding_right = make_finding(VerificationStatus.VERIFIED, "src/app.py", 11)
    finding_right.side = FindingSide.RIGHT
    assert (
        PositioningValidator.can_anchor_inline(finding_right, sample_parsed_diff)
        is True
    )

    # Line 11 is a deleted line on LEFT side
    finding_left = make_finding(VerificationStatus.VERIFIED, "src/app.py", 11)
    finding_left.side = FindingSide.LEFT
    assert (
        PositioningValidator.can_anchor_inline(finding_left, sample_parsed_diff) is True
    )


def test_positioning_validator_outside_diff_hunk(
    sample_parsed_diff: ParsedDiff,
) -> None:
    # Line 99 is far outside the diff hunk (lines 10-13)
    finding = make_finding(VerificationStatus.VERIFIED, "src/app.py", 99)
    assert PositioningValidator.can_anchor_inline(finding, sample_parsed_diff) is False


def test_positioning_validator_file_not_in_diff(sample_parsed_diff: ParsedDiff) -> None:
    # File not present in the diff
    finding = make_finding(VerificationStatus.VERIFIED, "src/other.py", 10)
    assert PositioningValidator.can_anchor_inline(finding, sample_parsed_diff) is False


def test_positioning_validator_diff_none() -> None:
    finding = make_finding(VerificationStatus.VERIFIED, "src/app.py", 10)
    assert PositioningValidator.can_anchor_inline(finding, None) is False


def test_partition_by_anchorable(sample_parsed_diff: ParsedDiff) -> None:
    f_anchorable = make_finding(VerificationStatus.VERIFIED, "src/app.py", 11)
    f_unanchored = make_finding(VerificationStatus.VERIFIED, "src/app.py", 99)
    f_missing_file = make_finding(VerificationStatus.VERIFIED, "src/other.py", 10)

    anchorable, unanchored = PositioningValidator.partition_by_anchorable(
        [f_anchorable, f_unanchored, f_missing_file], sample_parsed_diff
    )

    assert len(anchorable) == 1
    assert anchorable[0].finding_id == f_anchorable.finding_id
    assert len(unanchored) == 2
    assert {u.finding_id for u in unanchored} == {
        f_unanchored.finding_id,
        f_missing_file.finding_id,
    }
