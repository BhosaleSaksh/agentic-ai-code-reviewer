"""Critic Agent for evidence-grounded verification and false-positive reduction.

Evaluates candidate findings against concrete git diff hunks and normalized static analysis evidence,
assigning calibrated confidence scores and verified/rejected lifecycle statuses.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import ValidationError

from app.agents.critic_prompt import (
    CRITIC_SYSTEM_PROMPT,
    build_critic_user_prompt,
)
from app.orchestration.errors import (
    InvalidCriticOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.diff import ParsedDiff
from app.schemas.enums import VerificationStatus
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.verification import (
    CriticStructuredOutput,
    VerificationContext,
    VerificationResult,
)
from app.services.evidence.grounding_service import EvidenceGroundingService
from app.services.llm.service import LLMService

logger = logging.getLogger(__name__)


class CriticAgent:
    """Critic and Verification Agent verifying candidate code review findings."""

    def __init__(
        self,
        llm_service: LLMService | None = None,
        grounding_service: EvidenceGroundingService | None = None,
    ) -> None:
        self.llm_service = llm_service or LLMService()
        self.grounding_service = grounding_service or EvidenceGroundingService()

    async def verify_finding(self, context: VerificationContext) -> VerificationResult:
        """Verify a single candidate finding against its structured VerificationContext.

        Args:
            context: Bounded verification context with diff excerpts and static evidence.

        Returns:
            VerificationResult: Calibrated verification decision (VERIFIED or REJECTED).
        """
        finding = context.candidate_finding
        finding_id = str(finding.finding_id)

        # 1. Check if deterministically disqualified prior to LLM
        if context.deterministic_rejection_reason is not None:
            logger.info(
                "CriticAgent returning deterministic rejection for finding %s: %s",
                finding_id,
                context.deterministic_rejection_reason,
            )
            res = VerificationResult(
                finding_id=finding.finding_id,
                verification_status=VerificationStatus.REJECTED,
                confidence_score=0.0,
                evidence_sufficiency=False,
                contradiction_detected=True,
                rejected_reasons=[context.deterministic_rejection_reason],
                verifier_notes=f"Deterministically rejected: {context.deterministic_rejection_reason}",
                calibrated_by="deterministic_validator",
                deterministic_validation_passed=False,
            )
            self.grounding_service.apply_verification_to_finding(finding, res)
            return res

        # 2. Render prompt and invoke LLM
        start_time = time.monotonic()
        user_prompt = build_critic_user_prompt(context)

        logger.info(
            "CriticAgent verifying finding: id=%s, file=%s, line=%d, originating_agent=%s",
            finding_id,
            finding.affected_file,
            finding.line_number,
            context.agent_provenance or "unknown",
        )

        try:
            llm_result, _metadata = await self.llm_service.generate_structured(
                prompt=user_prompt,
                schema=CriticStructuredOutput,
                system_prompt=CRITIC_SYSTEM_PROMPT,
            )
        except (LLMTimeoutError, LLMProviderError):
            raise
        except ValidationError as exc:
            raise InvalidCriticOutputError(
                message=f"Critic LLM output failed schema validation for finding {finding_id}: {exc}",
                finding_id=finding_id,
                validation_errors=exc.errors(),
            ) from exc
        except Exception as exc:
            raise InvalidCriticOutputError(
                message=f"Critic LLM output could not be parsed for finding {finding_id}: {exc}",
                finding_id=finding_id,
            ) from exc

        duration = time.monotonic() - start_time
        logger.info(
            "CriticAgent LLM verification completed: id=%s, decision=%s, confidence=%.2f, duration=%.2fs",
            finding_id,
            llm_result.decision,
            llm_result.calibrated_confidence,
            duration,
        )

        # 3. Synthesize decision using EvidenceGroundingService
        verification_result = self.grounding_service.synthesize_verification_decision(
            context=context,
            llm_output=llm_result,
        )

        # Update finding in-place
        self.grounding_service.apply_verification_to_finding(
            finding, verification_result
        )

        return verification_result

    async def verify_candidate(
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
    ) -> VerificationResult:
        """Prepare context, run deterministic gates, and verify candidate finding end-to-end."""
        can_proceed, deterministic_rejection, context = (
            self.grounding_service.prepare_verification_context(
                finding=finding,
                parsed_diff=parsed_diff,
                changed_files=changed_files,
                review_run_id=review_run_id,
                repository_full_name=repository_full_name,
                commit_sha=commit_sha,
                base_sha=base_sha,
                expected_commit_sha=expected_commit_sha,
                evidence_items=evidence_items,
            )
        )

        if not can_proceed and deterministic_rejection is not None:
            self.grounding_service.apply_verification_to_finding(
                finding, deterministic_rejection
            )
            return deterministic_rejection

        return await self.verify_finding(context)
