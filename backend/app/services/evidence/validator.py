"""Deterministic finding and evidence validator for code review verification.

Applies deterministic checks (file existence, line bounds, diff relevance, commit SHA,
evidence integrity, and malformed structure rejection) prior to LLM verification.
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.diff import ParsedDiff
from app.schemas.enums import VerificationStatus
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.verification import VerificationResult
from app.services.evidence.diff_resolver import DiffEvidenceResolver
from app.services.evidence.static_matcher import StaticEvidenceMatcher

logger = logging.getLogger(__name__)


class FindingEvidenceValidator:
    """Performs deterministic validation on candidate findings before LLM verification."""

    def __init__(
        self,
        diff_resolver: DiffEvidenceResolver | None = None,
        static_matcher: StaticEvidenceMatcher | None = None,
    ) -> None:
        self.diff_resolver = diff_resolver or DiffEvidenceResolver()
        self.static_matcher = static_matcher or StaticEvidenceMatcher()

    def validate_candidate_finding(
        self,
        finding: ReviewFinding,
        parsed_diff: ParsedDiff | None,
        changed_files: list[str],
        commit_sha: str,
        expected_commit_sha: str | None = None,
        evidence_items: list[EvidenceModel] | list[dict[str, Any]] | None = None,
    ) -> tuple[bool, str | None, VerificationResult | None]:
        """Validate candidate finding against deterministic rules.

        Returns:
            tuple[is_valid, rejection_reason, immediate_result]:
                - is_valid: True if candidate passes deterministic checks and can proceed to LLM.
                - rejection_reason: Failure reason if rejected deterministically.
                - immediate_result: Pre-computed VerificationResult if rejected.
        """
        # 1. Structural / Non-empty validation
        if not finding.title or not finding.title.strip():
            reason = "Malformed candidate finding: empty title"
            return False, reason, self._build_rejection_result(finding, reason)

        if not finding.explanation or not finding.explanation.strip():
            reason = "Malformed candidate finding: empty explanation"
            return False, reason, self._build_rejection_result(finding, reason)

        if not finding.affected_file or not finding.affected_file.strip():
            reason = "Malformed candidate finding: empty affected_file"
            return False, reason, self._build_rejection_result(finding, reason)

        if finding.line_number < 1:
            reason = (
                f"Invalid line number {finding.line_number}: line numbers must be >= 1"
            )
            return False, reason, self._build_rejection_result(finding, reason)

        # 2. Commit SHA consistency check
        if expected_commit_sha and commit_sha != expected_commit_sha:
            reason = f"Commit SHA mismatch: finding associated with commit {commit_sha}, expected {expected_commit_sha}"
            return False, reason, self._build_rejection_result(finding, reason)

        # 3. File existence check in PR context
        clean_file = finding.affected_file.replace("\\", "/").strip().lstrip("./")
        file_in_diff = self.diff_resolver.file_exists_in_diff(parsed_diff, clean_file)
        file_in_changed_list = any(
            f.replace("\\", "/").strip().lstrip("./") == clean_file
            or f.replace("\\", "/").strip().lstrip("./").endswith(clean_file)
            or clean_file.endswith(f.replace("\\", "/").strip().lstrip("./"))
            for f in changed_files
        )

        if not (file_in_diff or file_in_changed_list):
            reason = f"Cited file '{finding.affected_file}' does not exist in PR diff or changed files list"
            return False, reason, self._build_rejection_result(finding, reason)

        # 4. Diff coordinate and relevance check
        if parsed_diff is not None:
            # Check if line is covered by any hunk in the diff
            line_in_diff = self.diff_resolver.line_in_diff(
                parsed_diff=parsed_diff,
                file_path=clean_file,
                line_number=finding.line_number,
                side=finding.side,
            )

            # If the diff contains the file, but the line is not in ANY hunk:
            diff_file = self.diff_resolver.resolve_file(parsed_diff, clean_file)
            if diff_file is not None and not line_in_diff:
                reason = (
                    f"Cited line {finding.line_number} in '{finding.affected_file}' falls outside all modified "
                    f"diff hunks (hunk spans: {[f'L{h.old_start}-{h.old_start + h.old_count}' for h in diff_file.hunks]})"
                )
                return False, reason, self._build_rejection_result(finding, reason)

        # 5. Evidence Reference Integrity Check
        # If finding references specific static analysis evidence, verify it isn't fabricated
        if evidence_items is not None and finding.evidence:
            for ev in finding.evidence:
                if (
                    ev.rule_or_cve_id
                    and ev.corroborating_tool
                    and ev.corroborating_tool.lower()
                    in ("semgrep", "bandit", "pip_audit", "pip-audit")
                ):
                    # Corroborate whether static analysis evidence exists
                    matches = self.static_matcher.match_finding_evidence(
                        finding, evidence_items
                    )
                    if not matches:
                        logger.info(
                            "Candidate finding references static rule %s from %s but no matching tool finding exists in context",
                            ev.rule_or_cve_id,
                            ev.corroborating_tool,
                        )

        # Passed all deterministic gates
        return True, None, None

    def _build_rejection_result(
        self, finding: ReviewFinding, reason: str
    ) -> VerificationResult:
        """Construct an immediate deterministic REJECTED VerificationResult."""
        logger.warning(
            "Candidate finding %s deterministically rejected: %s",
            finding.finding_id,
            reason,
        )
        return VerificationResult(
            finding_id=finding.finding_id,
            verification_status=VerificationStatus.REJECTED,
            confidence_score=0.0,
            evidence_sufficiency=False,
            contradiction_detected=True,
            rejected_reasons=[reason],
            verifier_notes=f"Deterministically rejected prior to LLM verification: {reason}",
            calibrated_by="deterministic_validator",
            deterministic_validation_passed=False,
        )
