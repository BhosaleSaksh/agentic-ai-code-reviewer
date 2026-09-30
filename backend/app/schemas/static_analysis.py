"""Tool-specific static analysis schemas for Phase 2.1.

Defines strongly typed result models and finding representations for containerized
Semgrep and Bandit static analysis runners.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StaticAnalysisExecutionStatus(StrEnum):
    """Execution status for containerized static analysis tools."""

    SUCCESS_NO_FINDINGS = "SUCCESS_NO_FINDINGS"
    SUCCESS_WITH_FINDINGS = "SUCCESS_WITH_FINDINGS"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    TIMEOUT = "TIMEOUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"


class SemgrepFinding(BaseModel):
    """Raw structured finding emitted by Semgrep."""

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(description="Unique rule identifier / check_id")
    message: str = Field(description="Human-readable rule explanation")
    severity: str = Field(description="Semgrep severity level: INFO, WARNING, or ERROR")
    file_path: str = Field(description="Normalized workspace-relative file path")
    start_line: int = Field(ge=1, description="1-indexed starting line")
    end_line: int = Field(ge=1, description="1-indexed ending line")
    start_col: int | None = Field(default=None, description="1-indexed start column")
    end_col: int | None = Field(default=None, description="1-indexed end column")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Rule metadata including CWE, OWASP, and references",
    )
    raw_json: dict[str, Any] | None = Field(
        default=None,
        description="Original finding object from Semgrep JSON",
    )


class SemgrepResult(BaseModel):
    """Structured execution result of the Semgrep analyzer."""

    model_config = ConfigDict(frozen=True)

    analyzer: str = Field(default="semgrep", description="Analyzer name")
    analyzer_version: str = Field(description="Pinned Semgrep version")
    execution_status: StaticAnalysisExecutionStatus = Field(
        description="Deterministic execution status"
    )
    exit_code: int | None = Field(
        default=None,
        description="Container exit code, if process completed",
    )
    duration_seconds: float = Field(
        ge=0.0,
        description="Execution wall-clock duration in seconds",
    )
    workspace_commit_sha: str = Field(
        description="Commit SHA of analyzed workspace snapshot",
    )
    findings: list[SemgrepFinding] = Field(
        default_factory=list,
        description="List of detected Semgrep findings",
    )
    error_message: str | None = Field(
        default=None,
        description="Diagnostic or error message if execution failed",
    )
    raw_stderr: str | None = Field(
        default=None,
        description="Truncated stderr diagnostics for troubleshooting",
    )


class BanditFinding(BaseModel):
    """Raw structured finding emitted by Bandit."""

    model_config = ConfigDict(frozen=True)

    test_id: str = Field(description="Bandit test ID (e.g. B101, B307, B608)")
    test_name: str = Field(
        description="Bandit test plugin name (e.g. eval, assert_used)"
    )
    issue_text: str = Field(description="Description of the security issue")
    severity: str = Field(description="Bandit severity rating: LOW, MEDIUM, or HIGH")
    confidence: str = Field(
        description="Bandit confidence rating: LOW, MEDIUM, or HIGH"
    )
    file_path: str = Field(description="Normalized workspace-relative file path")
    line_number: int = Field(
        ge=1, description="1-indexed line number where issue occurred"
    )
    line_range: list[int] = Field(
        default_factory=list,
        description="Inclusive line range where issue is located",
    )
    code: str | None = Field(
        default=None, description="Source code snippet triggering issue"
    )
    more_info: str | None = Field(
        default=None,
        description="Documentation or CWE URL for the Bandit rule",
    )
    raw_json: dict[str, Any] | None = Field(
        default=None,
        description="Original finding object from Bandit JSON",
    )


class BanditResult(BaseModel):
    """Structured execution result of the Bandit analyzer."""

    model_config = ConfigDict(frozen=True)

    analyzer: str = Field(default="bandit", description="Analyzer name")
    analyzer_version: str = Field(description="Pinned Bandit version")
    execution_status: StaticAnalysisExecutionStatus = Field(
        description="Deterministic execution status"
    )
    exit_code: int | None = Field(
        default=None,
        description="Container exit code, if process completed",
    )
    duration_seconds: float = Field(
        ge=0.0,
        description="Execution wall-clock duration in seconds",
    )
    workspace_commit_sha: str = Field(
        description="Commit SHA of analyzed workspace snapshot",
    )
    findings: list[BanditFinding] = Field(
        default_factory=list,
        description="List of detected Bandit findings",
    )
    error_message: str | None = Field(
        default=None,
        description="Diagnostic or error message if execution failed",
    )
    raw_stderr: str | None = Field(
        default=None,
        description="Truncated stderr diagnostics for troubleshooting",
    )


class PipAuditFinding(BaseModel):
    """Raw structured dependency vulnerability finding emitted by pip-audit."""

    model_config = ConfigDict(frozen=True)

    package_name: str = Field(description="Name of the vulnerable package")
    package_version: str | None = Field(
        default=None,
        description="Installed or declared version of the package",
    )
    vuln_id: str = Field(
        description="Vulnerability identifier (e.g. PYSEC-2021-123, GHSA-xxxx-xxxx)"
    )
    description: str | None = Field(
        default=None,
        description="Detailed description or advisory text of the vulnerability",
    )
    fix_versions: list[str] = Field(
        default_factory=list,
        description="Package versions containing the fix",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative advisory or CVE identifiers (e.g. CVE-2021-4321)",
    )
    dependency_file: str = Field(
        description="Normalized workspace-relative path to the dependency declaration file (e.g. requirements.txt)",
    )
    line_number: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed line number in the dependency file where package is declared, if determined",
    )
    raw_json: dict[str, Any] | None = Field(
        default=None,
        description="Original finding object from pip-audit JSON",
    )


class PipAuditResult(BaseModel):
    """Structured execution result of the pip-audit analyzer."""

    model_config = ConfigDict(frozen=True)

    analyzer: str = Field(default="pip-audit", description="Analyzer name")
    analyzer_version: str = Field(description="Pinned pip-audit version")
    execution_status: StaticAnalysisExecutionStatus = Field(
        description="Deterministic execution status"
    )
    exit_code: int | None = Field(
        default=None,
        description="Container exit code, if process completed",
    )
    duration_seconds: float = Field(
        ge=0.0,
        description="Execution wall-clock duration in seconds",
    )
    workspace_commit_sha: str = Field(
        description="Commit SHA of analyzed workspace snapshot",
    )
    dependency_files_scanned: list[str] = Field(
        default_factory=list,
        description="Workspace-relative paths of dependency manifests inspected",
    )
    findings: list[PipAuditFinding] = Field(
        default_factory=list,
        description="List of detected dependency vulnerabilities",
    )
    error_message: str | None = Field(
        default=None,
        description="Diagnostic or error message if execution failed",
    )
    raw_stderr: str | None = Field(
        default=None,
        description="Truncated stderr diagnostics for troubleshooting",
    )


class ToolAnalysisSummary(BaseModel):
    """Structured aggregation of Phase 2.1 and Phase 2.2 tool-specific results."""

    model_config = ConfigDict(frozen=True)

    semgrep: SemgrepResult = Field(description="Semgrep execution result")
    bandit: BanditResult = Field(description="Bandit execution result")
    pip_audit: PipAuditResult | None = Field(
        default=None,
        description="pip-audit execution result",
    )
    workspace_commit_sha: str = Field(description="Target commit SHA analyzed")
    duration_seconds: float = Field(
        ge=0.0,
        description="Total duration spanning all static analysis execution",
    )
