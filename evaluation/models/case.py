"""Evaluation case schema, ground-truth models, and provenance metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DefectCategory(StrEnum):
    """Broad defect categorization for benchmark evaluation."""

    SECURITY = "SECURITY"
    BUG_LOGIC = "BUG_LOGIC"
    ERROR_HANDLING = "ERROR_HANDLING"
    TEST_ADEQUACY = "TEST_ADEQUACY"


class ExpectedSeverity(StrEnum):
    """Normalized severity grading expected by ground-truth benchmarks."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ExpectedEvidence(BaseModel):
    """Specification of expected evidence grounding corroboration."""

    model_config = ConfigDict(extra="ignore")

    tool_name: str | None = Field(
        default=None,
        description="Expected corroborating tool (e.g. bandit, semgrep, pip_audit)",
    )
    rule_or_cve_id: str | None = Field(
        default=None,
        description="Expected rule identifier or CVE (e.g. bandit.B608, CVE-2023-xxxx)",
    )
    target_pattern: str | None = Field(
        default=None,
        description="Code pattern or snippet expected to be isolated as evidence",
    )
    description: str | None = Field(
        default=None,
        description="Explanation of how the evidence supports the defect",
    )


class GroundTruthDefect(BaseModel):
    """Ground-truth specification for a single defect within an evaluation case."""

    model_config = ConfigDict(extra="ignore")

    defect_id: str = Field(description="Unique defect identifier within the case")
    category: DefectCategory = Field(description="High-level category")
    affected_file: str = Field(description="Normalized relative path to affected file")
    line_start: int = Field(ge=1, description="1-indexed starting line")
    line_end: int = Field(ge=1, description="1-indexed ending line")
    expected_issue_type: str = Field(
        description="Standardized issue type (e.g. SQL_INJECTION, BOUNDARY_ERROR)"
    )
    expected_severity: ExpectedSeverity = Field(
        default=ExpectedSeverity.MEDIUM,
        description="Expected severity grade",
    )
    description: str = Field(description="Short human summary of the defect")
    explanation: str = Field(description="Detailed ground-truth rationale")
    expected_evidence: list[ExpectedEvidence] = Field(
        default_factory=list,
        description="Expected static analysis or context evidence",
    )


class CaseProvenance(BaseModel):
    """Audit metadata tracking the origin, authorship, and licensing of an evaluation case."""

    model_config = ConfigDict(extra="ignore")

    source: str = Field(
        description="Origin of the case (e.g. synthetic_corpus, oss_cve, github_pr)"
    )
    author_or_curator: str = Field(
        default="benchmark_team",
        description="Entity or maintainer who curated the case",
    )
    created_at: str = Field(
        description="ISO-8601 timestamp of case creation or curation"
    )
    license: str = Field(
        default="MIT",
        description="License applying to the case code (e.g. MIT, Apache-2.0)",
    )
    reference_url: str | None = Field(
        default=None,
        description="Upstream PR URL, commit permalink, or CVE advisory",
    )
    repository: str | None = Field(
        default=None,
        description="Upstream repository name if real-world case (e.g. owner/repo)",
    )
    commit_sha: str | None = Field(
        default=None,
        description="Exact commit SHA where defect was observed",
    )
    ground_truth_authority: str = Field(
        default="curated_expert",
        description="Authority establishing ground truth (e.g. maintainer_fix, cve_advisory)",
    )
    annotation_uncertainty: str = Field(
        default="LOW",
        description="Confidence in ground truth label (LOW, MEDIUM, HIGH)",
    )
    notes: str | None = Field(
        default=None,
        description="Additional curation notes or edge-case context",
    )


class EvaluationInput(BaseModel):
    """Model and baseline input containing strictly what a real reviewer would legitimately receive.

    Ground-truth defect types, explanations, line coordinates, and severity expectations
    are strictly excluded. Any attempt to pass or access ground truth raises an error.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(description="Unique case identifier")
    category: DefectCategory = Field(description="High-level category context")
    title: str = Field(description="PR or code change title")
    description: str = Field(description="PR description or contextual summary")
    affected_file: str = Field(description="File path under review")
    vulnerable_code: str = Field(description="Source code or diff under review")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe metadata such as repository name or commit SHA",
    )


class EvaluationCase(BaseModel):
    """Complete evaluation case containing code under review and ground truth."""

    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(
        description="Globally unique case identifier (e.g. SYNTH-SEC-001)"
    )
    category: DefectCategory = Field(description="Primary category under test")
    title: str = Field(description="Human-readable case title")
    description: str = Field(description="Contextual overview of the PR/code change")
    vulnerable_code: str = Field(description="Source code or unified diff under test")
    affected_file: str = Field(description="Primary file path under review")
    fixed_code: str | None = Field(
        default=None,
        description="Reference corrected code if available",
    )
    ground_truth: list[GroundTruthDefect] = Field(
        default_factory=list,
        description="List of ground-truth defects present in the code",
    )
    provenance: CaseProvenance = Field(
        description="Provenance audit trail for the case",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional arbitrary metadata for extensible benchmark runners",
    )

    def to_evaluation_input(self) -> EvaluationInput:
        """Produce clean input context for reviewer models without ground truth leakage.

        Returns only the file name, code/diff content, and description, strictly
        omitting defect locations, severity expectations, and ground-truth explanations.
        """
        safe_meta: dict[str, Any] = {}
        if self.provenance.repository:
            safe_meta["repository"] = self.provenance.repository
        if self.provenance.commit_sha:
            safe_meta["commit_sha"] = self.provenance.commit_sha

        return EvaluationInput(
            case_id=self.case_id,
            category=self.category,
            title=self.title,
            description=self.description,
            affected_file=self.affected_file,
            vulnerable_code=self.vulnerable_code,
            metadata=safe_meta,
        )
