"""Validators for publication eligibility and diff positioning.

Enforces:
1. Strict Finding Eligibility Invariant: Only findings with VerificationStatus.VERIFIED
   may be published to GitHub. Any other status is rejected.
2. Safe Diff Positioning Invariant: Inline review comments are only published
   when the line coordinate safely falls within a valid hunk in the PR diff.
   Unanchored findings fall back to the top-level review summary without position fabrication.
"""

import logging

from app.schemas.diff import ParsedDiff
from app.schemas.enums import VerificationStatus
from app.schemas.finding import ReviewFinding
from app.services.github.errors import PublishValidationError

logger = logging.getLogger(__name__)


class FindingEligibilityValidator:
    """Independent validator ensuring only Critic-verified findings reach GitHub."""

    @staticmethod
    def is_eligible(finding: ReviewFinding) -> bool:
        """Check if a finding satisfies all publication eligibility criteria.

        Args:
            finding: Candidate or verified finding.

        Returns:
            bool: True if strictly VERIFIED, False otherwise.
        """
        return finding.verification_status == VerificationStatus.VERIFIED

    @classmethod
    def validate(cls, finding: ReviewFinding) -> None:
        """Enforce eligibility invariant, raising typed error if ineligible.

        Args:
            finding: ReviewFinding to validate.

        Raises:
            PublishValidationError: If finding is not in VERIFIED status.
        """
        if not cls.is_eligible(finding):
            logger.warning(
                "Publication rejected: Finding %s is %s (only VERIFIED findings may be published)",
                finding.finding_id,
                finding.verification_status,
            )
            raise PublishValidationError(
                message=(
                    f"Finding {finding.finding_id} is ineligible for GitHub publication: "
                    f"status is {finding.verification_status}, expected {VerificationStatus.VERIFIED}"
                ),
                details={
                    "finding_id": str(finding.finding_id),
                    "status": str(finding.verification_status),
                },
            )

    @classmethod
    def partition_findings(
        cls,
        findings: list[ReviewFinding],
    ) -> tuple[list[ReviewFinding], list[ReviewFinding]]:
        """Separate findings into eligible (VERIFIED) and ineligible.

        Args:
            findings: Input findings list.

        Returns:
            tuple[list[ReviewFinding], list[ReviewFinding]]: (eligible, ineligible)
        """
        eligible: list[ReviewFinding] = []
        ineligible: list[ReviewFinding] = []

        for f in findings:
            if cls.is_eligible(f):
                eligible.append(f)
            else:
                ineligible.append(f)

        return eligible, ineligible


class PositioningValidator:
    """Validates whether a finding can be safely anchored to a diff hunk."""

    @staticmethod
    def can_anchor_inline(
        finding: ReviewFinding,
        parsed_diff: ParsedDiff | None,
    ) -> bool:
        """Determine if a finding line can be safely anchored within the PR diff.

        Args:
            finding: Finding containing affected_file, line_number, and side.
            parsed_diff: Parsed unified diff of the PR.

        Returns:
            bool: True if line is inside a valid hunk in the diff; False otherwise.
        """
        if parsed_diff is None:
            return False

        return parsed_diff.is_line_in_diff(
            path=finding.affected_file,
            line_number=finding.line_number,
            side=finding.side,
        )

    @classmethod
    def partition_by_anchorable(
        cls,
        findings: list[ReviewFinding],
        parsed_diff: ParsedDiff | None,
    ) -> tuple[list[ReviewFinding], list[ReviewFinding]]:
        """Partition verified findings into anchorable inline comments and unanchored findings.

        Args:
            findings: List of verified ReviewFindings.
            parsed_diff: Parsed unified diff of the PR.

        Returns:
            tuple[list[ReviewFinding], list[ReviewFinding]]: (anchorable, unanchored)
        """
        anchorable: list[ReviewFinding] = []
        unanchored: list[ReviewFinding] = []

        for f in findings:
            if cls.can_anchor_inline(f, parsed_diff):
                anchorable.append(f)
            else:
                logger.info(
                    "Finding %s (%s:%d) is unanchored in diff; routing to review summary fallback",
                    f.finding_id,
                    f.affected_file,
                    f.line_number,
                )
                unanchored.append(f)

        return anchorable, unanchored
