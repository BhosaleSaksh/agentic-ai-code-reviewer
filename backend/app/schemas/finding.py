"""Canonical ReviewFinding schema representing code review findings.

Corresponds to Section J of the project architecture and the unified
Finding domain model, covering the complete lifecycle:
Candidate -> Critic Verification -> Persistence -> GitHub Publication.
"""

import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.schemas.enums import (
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel


class ReviewFinding(BaseModel):
    """Canonical data contract for an automated code review finding.

    This schema is enforced across all pipeline boundaries:
    - Specialist agent candidate findings
    - Critic / verification scoring and rejection
    - Database persistence mapping
    - GitHub PR review comment publishing
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    finding_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        alias="id",
        description="Unique identifier for the finding",
    )
    issue_type: IssueType = Field(
        ...,
        description="Category of the finding (SECURITY, BUG_LOGIC, etc.)",
    )
    severity: Severity = Field(
        ...,
        description="Severity classification (CRITICAL, HIGH, MEDIUM, LOW, INFO)",
    )
    affected_file: str = Field(
        ...,
        min_length=1,
        max_length=500,
        alias="file_path",
        description="Relative repository path of the affected file",
    )
    line_number: int = Field(
        ...,
        ge=1,
        description="1-based line number in the diff where comment attaches",
    )
    side: FindingSide = Field(
        default=FindingSide.RIGHT,
        description="Diff side: RIGHT for added/modified lines, LEFT for deleted lines",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Concise, actionable headline summarizing the issue",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        description="Detailed root-cause explanation and blast radius analysis",
    )
    evidence: list[EvidenceModel] = Field(
        default_factory=list,
        description="Verifiable evidence items grounding this finding",
    )
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence score (0.0 to 1.0) assigned after Critic pass",
    )
    recommendation: str = Field(
        ...,
        min_length=1,
        description="Prescriptive fix instructions for the PR author",
    )
    suggested_patch: str | None = Field(
        None,
        description="Optional GitHub suggestion block or replacement patch",
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Verification lifecycle status assigned by the Critic Agent",
    )
    critic_notes: str | None = Field(
        None,
        description="Reasoning trace or verification justification from the Critic Agent",
    )

    # Lifecycle provenance & persistence fields
    agent_name: str | None = Field(
        None,
        max_length=50,
        description="Name of the specialist agent that originated the candidate finding",
    )
    raw_confidence: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Pre-critic confidence emitted directly by the specialist agent",
    )
    rejection_reason: str | None = Field(
        None,
        description="Reason for suppression or drop if rejected during critic verification",
    )
    publish_status: PublishStatus = Field(
        default=PublishStatus.UNPUBLISHED,
        description="GitHub publication status (UNPUBLISHED, PUBLISHED, FAILED, DISMISSED)",
    )
    github_comment_id: int | None = Field(
        None,
        description="GitHub Review Comment ID if published to the PR",
    )

    @field_validator(
        "issue_type", "severity", "side", "verification_status", mode="before"
    )
    @classmethod
    def normalize_enum_case(cls, v: object) -> object:
        """Normalize string representations of enums to uppercase."""
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("confidence_score")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Round calibrated confidence score to 3 decimal places."""
        return round(v, 3)

    @field_validator("raw_confidence")
    @classmethod
    def validate_raw_confidence(cls, v: float | None) -> float | None:
        """Round raw confidence score to 3 decimal places if present."""
        if v is not None:
            return round(v, 3)
        return None

    @field_validator("affected_file")
    @classmethod
    def validate_affected_file(cls, v: str) -> str:
        """Ensure affected file is non-empty and contains no null bytes."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("affected_file cannot be blank")
        if "\x00" in cleaned:
            raise ValueError("affected_file cannot contain null bytes")
        return cleaned

    @field_validator("title", "explanation", "recommendation")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        """Ensure string fields contain non-whitespace text."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or purely whitespace")
        return cleaned

    @property
    def file_path(self) -> str:
        """Convenience property for accessing the affected file path."""
        return self.affected_file

    @property
    def is_verified(self) -> bool:
        """Check if finding has been successfully verified by the Critic."""
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def is_suppressed(self) -> bool:
        """Check if finding was suppressed as false positive or dropped."""
        return self.verification_status in (
            VerificationStatus.SUPPRESSED_FALSE_POSITIVE,
            VerificationStatus.DROPPED_LOW_CONFIDENCE,
        )

    @property
    def is_rejected(self) -> bool:
        """Check if finding was rejected during verification."""
        return self.verification_status in (
            VerificationStatus.REJECTED,
            VerificationStatus.SUPPRESSED_FALSE_POSITIVE,
            VerificationStatus.DROPPED_LOW_CONFIDENCE,
        )

    @property
    def is_published(self) -> bool:
        """Check if finding has been published to GitHub."""
        return self.publish_status == PublishStatus.PUBLISHED
