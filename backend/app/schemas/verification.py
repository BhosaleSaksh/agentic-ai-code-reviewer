"""Schemas for the verification decision model and evidence grounding context.

Corresponds to Phase 4 (Critic / Verification Agent & Evidence Grounding Engine)
defining structured contracts for deterministic and LLM-assisted verification.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import EvidenceType, VerificationStatus
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding


class EvidenceMatch(BaseModel):
    """Details of an evidence item that corroborates or contradicts a finding."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    evidence_type: EvidenceType = Field(
        ...,
        description="Type of evidence matched (DIFF_HUNK, STATIC_ANALYSIS, etc.)",
    )
    file_path: str = Field(
        ...,
        description="Path of the target file associated with this evidence",
    )
    start_line: int = Field(
        ...,
        description="1-based starting line number in the target file",
    )
    end_line: int = Field(
        ...,
        description="1-based ending line number in the target file",
    )
    snippet: str = Field(
        ...,
        description="Code snippet or diff hunk excerpt",
    )
    corroborating_tool: str | None = Field(
        None,
        description="Tool name (e.g. semgrep, bandit, pip_audit)",
    )
    rule_or_cve_id: str | None = Field(
        None,
        description="Rule ID or CVE ID from static analysis",
    )
    is_direct_match: bool = Field(
        default=True,
        description="True if coordinates match the finding exactly; False if proximate/inferred",
    )
    contradicts: bool = Field(
        default=False,
        description="True if this evidence contradicts the defect claim",
    )
    notes: str | None = Field(
        None,
        description="Observations regarding this evidence match",
    )


class VerificationContext(BaseModel):
    """Structured context assembled for deterministic and LLM verification of a finding."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    review_run_id: str = Field(
        ...,
        description="Review run execution identifier",
    )
    repository_full_name: str = Field(
        ...,
        description="Repository name in 'owner/repo' format",
    )
    commit_sha: str = Field(
        ...,
        description="Head commit SHA under review",
    )
    base_sha: str | None = Field(
        None,
        description="Base commit SHA",
    )
    candidate_finding: ReviewFinding = Field(
        ...,
        description="The candidate ReviewFinding to evaluate",
    )

    # Deterministic signals
    file_exists: bool = Field(
        default=False,
        description="True if affected_file exists in PR diff or changed files",
    )
    line_in_diff: bool = Field(
        default=False,
        description="True if cited line is within any hunk of the diff",
    )
    line_in_changed_hunk: bool = Field(
        default=False,
        description="True if cited line was actively modified/added/deleted in the diff",
    )
    diff_snippet: str | None = Field(
        None,
        description="Extracted unified diff excerpt around the cited line",
    )
    surrounding_code: str | None = Field(
        None,
        description="Clean source code lines around the cited line if resolvable",
    )
    hunk_header: str | None = Field(
        None,
        description="Diff hunk header (e.g. '@@ -10,5 +10,6 @@')",
    )

    # Corroborating evidence
    correlated_static_evidence: list[EvidenceModel] = Field(
        default_factory=list,
        description="Static analysis evidence matching the file/line",
    )
    agent_provenance: str | None = Field(
        None,
        description="Name of specialist agent that originated the candidate finding",
    )
    raw_confidence: float | None = Field(
        None,
        description="Specialist agent's pre-critic confidence score",
    )
    deterministic_rejection_reason: str | None = Field(
        None,
        description="If deterministically disqualified, the precise reason",
    )


class VerificationResult(BaseModel):
    """Canonical structured outcome of evaluating a single candidate finding."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    finding_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the evaluated candidate finding",
    )
    verification_status: VerificationStatus = Field(
        ...,
        description="Final verification decision: VERIFIED, REJECTED, or UNVERIFIED",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence score (0.0 to 1.0) derived by the Critic",
    )
    evidence_sufficiency: bool = Field(
        default=False,
        description="True if available evidence is sufficient to justify the claim",
    )
    evidence_matches: list[EvidenceMatch] = Field(
        default_factory=list,
        description="Matches against diff hunks, static analysis, or repo context",
    )
    contradiction_detected: bool = Field(
        default=False,
        description="True if code context contradicts the candidate finding's claim",
    )
    verification_reasons: list[str] = Field(
        default_factory=list,
        description="Arguments supporting the verification decision",
    )
    rejected_reasons: list[str] = Field(
        default_factory=list,
        description="Arguments justifying rejection or suppression",
    )
    verified_evidence: list[EvidenceModel] = Field(
        default_factory=list,
        description="Validated evidence items attached to the final finding",
    )
    verifier_notes: str | None = Field(
        None,
        description="Structured reasoning or verification trace from the Critic",
    )
    calibrated_by: str = Field(
        default="critic_agent",
        description="Agent or engine that performed the calibration",
    )
    deterministic_validation_passed: bool = Field(
        default=True,
        description="True if file, line, and diff checks passed deterministically",
    )

    @field_validator("confidence_score")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        """Round confidence score to 3 decimal places."""
        return round(v, 3)

    @property
    def is_verified(self) -> bool:
        """Return True if decision is VERIFIED."""
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def is_rejected(self) -> bool:
        """Return True if decision is REJECTED or suppressed."""
        return self.verification_status in (
            VerificationStatus.REJECTED,
            VerificationStatus.SUPPRESSED_FALSE_POSITIVE,
            VerificationStatus.DROPPED_LOW_CONFIDENCE,
        )


class CriticStructuredOutput(BaseModel):
    """Pydantic schema for structured output returned by the Critic LLM."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    decision: str = Field(
        default="VERIFIED",
        description="VERIFIED or REJECTED",
    )
    calibrated_confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence score between 0.0 and 1.0",
    )
    evidence_sufficiency: bool = Field(
        default=True,
        description="True if cited diff and context sufficiently substantiate the defect",
    )
    contradiction_detected: bool = Field(
        default=False,
        description="True if repository context reveals the claim is false or inapplicable",
    )
    critic_notes: str = Field(
        default="Substantiated defect grounded in code diff evidence.",
        min_length=1,
        description="Detailed verification analysis explaining the decision",
    )
    verification_reasons: list[str] = Field(
        default_factory=list,
        description="List of specific supporting evidence points",
    )
    rejection_reasons: list[str] = Field(
        default_factory=list,
        description="List of specific counter-evidence points or missing requirements",
    )

    @field_validator("decision")
    @classmethod
    def normalize_decision(cls, v: str) -> str:
        """Normalize decision string to uppercase."""
        normalized = v.strip().upper()
        if normalized not in ("VERIFIED", "REJECTED", "UNVERIFIED"):
            if "VERIF" in normalized:
                return "VERIFIED"
            return "REJECTED"
        return normalized
