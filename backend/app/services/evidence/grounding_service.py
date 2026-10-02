"""Evidence Grounding Engine coordinating deterministic verification, diff resolution, and static evidence correlation."""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.diff import ParsedDiff
from app.schemas.enums import VerificationStatus
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.verification import (
    CriticStructuredOutput,
    VerificationContext,
    VerificationResult,
)
from app.services.evidence.diff_resolver import DiffEvidenceResolver
from app.services.evidence.static_matcher import StaticEvidenceMatcher
from app.services.evidence.validator import FindingEvidenceValidator

logger = logging.getLogger(__name__)


class EvidenceGroundingService:
    """Core evidence-grounding service preparing structured verification contexts and evaluating evidence sufficiency."""

    def __init__(
        self,
        diff_resolver: DiffEvidenceResolver | None = None,
        static_matcher: StaticEvidenceMatcher | None = None,
        validator: FindingEvidenceValidator | None = None,
        verification_confidence_threshold: float = 0.70,
    ) -> None:
        self.diff_resolver = diff_resolver or DiffEvidenceResolver()
        self.static_matcher = static_matcher or StaticEvidenceMatcher()
        self.validator = validator or FindingEvidenceValidator(
            diff_resolver=self.diff_resolver,
            static_matcher=self.static_matcher,
        )
        self.confidence_threshold = verification_confidence_threshold

    def prepare_verification_context(
        self,
        finding: ReviewFinding,
        parsed_diff: ParsedDiff | None,
        changed_files: list[str],
        review_run_id: str,
        repository_full_name: str,
        commit_sha: str,
        base_sha: str | None = None,
        expected_commit_sha: str | None = None,
        evidence_items: list[EvidenceModel] | list[dict[str, Any]] | None = None,
    ) -> tuple[bool, VerificationResult | None, VerificationContext]:
        """Validate candidate finding deterministically and prepare structured VerificationContext.

        Returns:
            tuple[can_proceed_to_critic, deterministic_rejection_result, verification_context]:
                - can_proceed_to_critic: True if deterministic gates passed.
                - deterministic_rejection_result: VerificationResult if deterministically rejected.
                - verification_context: Complete bounded context for CriticAgent.
        """
        # 1. Deterministic validation
        is_valid, reject_reason, rejection_result = (
            self.validator.validate_candidate_finding(
                finding=finding,
                parsed_diff=parsed_diff,
                changed_files=changed_files,
                commit_sha=commit_sha,
                expected_commit_sha=expected_commit_sha,
                evidence_items=evidence_items,
            )
        )

        # 2. Resolve diff coordinates and excerpts
        clean_file = finding.affected_file.replace("\\", "/").strip().lstrip("./")
        file_exists = self.diff_resolver.file_exists_in_diff(parsed_diff, clean_file)
        line_in_diff = self.diff_resolver.line_in_diff(
            parsed_diff, clean_file, finding.line_number, finding.side
        )
        line_is_changed = self.diff_resolver.is_changed_line(
            parsed_diff, clean_file, finding.line_number, finding.side
        )
        diff_snippet, hunk_header = self.diff_resolver.extract_diff_excerpt(
            parsed_diff,
            clean_file,
            finding.line_number,
            context_window=4,
            side=finding.side,
        )
        surrounding_code = self.diff_resolver.extract_surrounding_code(
            parsed_diff,
            clean_file,
            finding.line_number,
            context_window=4,
            side=finding.side,
        )

        # 3. Match static analysis evidence
        correlated_evidence: list[EvidenceModel] = []
        if evidence_items:
            correlated_evidence = (
                self.static_matcher.extract_correlated_evidence_models(
                    finding=finding,
                    available_evidence=evidence_items,
                )
            )

        context = VerificationContext(
            review_run_id=review_run_id,
            repository_full_name=repository_full_name,
            commit_sha=commit_sha,
            base_sha=base_sha,
            candidate_finding=finding,
            file_exists=file_exists,
            line_in_diff=line_in_diff,
            line_in_changed_hunk=line_is_changed,
            diff_snippet=diff_snippet,
            surrounding_code=surrounding_code,
            hunk_header=hunk_header,
            correlated_static_evidence=correlated_evidence,
            agent_provenance=finding.agent_name,
            raw_confidence=finding.raw_confidence,
            deterministic_rejection_reason=reject_reason,
        )

        if not is_valid and rejection_result is not None:
            return False, rejection_result, context

        return True, None, context

    def synthesize_verification_decision(
        self,
        context: VerificationContext,
        llm_output: CriticStructuredOutput,
    ) -> VerificationResult:
        """Combine deterministic evidence signals with Critic LLM output to produce a calibrated VerificationResult."""
        finding = context.candidate_finding
        finding_id = finding.finding_id

        # 1. Determine calibrated confidence score
        calibrated_score = self.calibrate_confidence(context, llm_output)

        # 2. Evaluate verification status under conservative policy
        is_verified = (
            llm_output.decision == "VERIFIED"
            and llm_output.evidence_sufficiency is True
            and not llm_output.contradiction_detected
            and calibrated_score >= self.confidence_threshold
            and context.line_in_diff
        )

        status: VerificationStatus
        rejected_reasons: list[str] = list(llm_output.rejection_reasons)

        if is_verified:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.REJECTED
            if not context.line_in_diff:
                rejected_reasons.append("Cited line is not within the PR diff")
            if llm_output.contradiction_detected:
                rejected_reasons.append(
                    "Contradiction detected in repository code context"
                )
            if not llm_output.evidence_sufficiency:
                rejected_reasons.append(
                    "Insufficient evidence to substantiate defect claim"
                )
            if calibrated_score < self.confidence_threshold:
                rejected_reasons.append(
                    f"Calibrated confidence ({calibrated_score:.2f}) below verification threshold ({self.confidence_threshold:.2f})"
                )

        # 3. Assemble validated evidence items
        verified_evidence: list[EvidenceModel] = list(finding.evidence)
        if context.correlated_static_evidence:
            for static_ev in context.correlated_static_evidence:
                if static_ev not in verified_evidence:
                    verified_evidence.append(static_ev)

        return VerificationResult(
            finding_id=finding_id,
            verification_status=status,
            confidence_score=calibrated_score,
            evidence_sufficiency=llm_output.evidence_sufficiency,
            contradiction_detected=llm_output.contradiction_detected,
            verification_reasons=list(llm_output.verification_reasons),
            rejected_reasons=rejected_reasons,
            verified_evidence=verified_evidence,
            verifier_notes=llm_output.critic_notes,
            calibrated_by="critic_agent",
            deterministic_validation_passed=True,
        )

    def calibrate_confidence(
        self,
        context: VerificationContext,
        llm_output: CriticStructuredOutput,
    ) -> float:
        """Calculate explainable, evidence-grounded confidence score.

        Weights deterministic signals (exact changed line, static tool correlation)
        together with the Critic's assessment.
        """
        # Base confidence from Critic
        score = llm_output.calibrated_confidence

        # Bonus for exact changed line in diff
        if context.line_in_changed_hunk:
            score = min(1.0, score + 0.05)
        elif not context.line_in_diff:
            # Heavy penalty if line is completely outside diff
            score = max(0.0, score - 0.40)

        # Bonus for corroborating static analysis finding
        if context.correlated_static_evidence:
            score = min(1.0, score + 0.10)

        # Penalty for contradiction
        if llm_output.contradiction_detected:
            score = max(0.0, score - 0.50)

        # Penalty if evidence is insufficient
        if not llm_output.evidence_sufficiency:
            score = min(score, 0.45)

        return round(score, 3)

    def apply_verification_to_finding(
        self,
        finding: ReviewFinding,
        result: VerificationResult,
    ) -> ReviewFinding:
        """Update a ReviewFinding in-place with the outcome of verification."""
        finding.verification_status = result.verification_status
        finding.confidence_score = result.confidence_score
        finding.critic_notes = result.verifier_notes
        if result.rejected_reasons:
            finding.rejection_reason = "; ".join(result.rejected_reasons)
        if result.verified_evidence:
            finding.evidence = result.verified_evidence
        return finding
