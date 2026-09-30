"""Evidence schema representing verifiable artifacts supporting review findings.

Corresponds to the 4 pillars of evidence grounding defined in Section I
of the project architecture: DiffEvidence, StaticToolEvidence,
DependencyEvidence, and ContextEvidence.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import EvidenceType


class EvidenceModel(BaseModel):
    """Canonical evidence item grounding a code review finding.

    Every finding published to developers must be substantiated by at least
    one verifiable evidence item (diff coordinates, static tool rule ID,
    dependency advisory, or enclosing AST context).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    evidence_type: EvidenceType = Field(
        ...,
        description="Pillar of evidence: DIFF_HUNK, STATIC_ANALYSIS, DEPENDENCY, or AST_CONTEXT",
    )
    file_path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Path of the target file associated with this evidence",
    )
    start_line: int = Field(
        ...,
        ge=1,
        description="1-based starting line number in the target file",
    )
    end_line: int = Field(
        ...,
        ge=1,
        description="1-based ending line number in the target file",
    )
    snippet: str = Field(
        ...,
        min_length=1,
        alias="content_snippet",
        description="Code snippet, diff hunk excerpt, or AST context excerpt",
    )
    rule_or_cve_id: str | None = Field(
        None,
        max_length=100,
        description="Deterministic static analysis rule ID (e.g. bandit.B608) or CVE ID",
    )
    corroborating_tool: str | None = Field(
        None,
        max_length=50,
        description="Name of the static tool or analyzer providing evidence (e.g. semgrep, bandit)",
    )
    metadata: dict[str, Any] | None = Field(
        None,
        alias="extra_metadata",
        description="Additional structured context (e.g. raw tool output, AST caller graph)",
    )

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v: str) -> str:
        """Ensure file path is non-empty and contains no null bytes."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("file_path cannot be blank")
        if "\x00" in cleaned:
            raise ValueError("file_path cannot contain null bytes")
        return cleaned

    @field_validator("snippet")
    @classmethod
    def validate_snippet(cls, v: str) -> str:
        """Ensure snippet contains non-whitespace content."""
        if not v.strip():
            raise ValueError("snippet cannot be empty or purely whitespace")
        return v

    @model_validator(mode="after")
    def validate_line_range(self) -> "EvidenceModel":
        """Verify that end_line is greater than or equal to start_line."""
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) cannot be less than start_line ({self.start_line})"
            )
        return self
