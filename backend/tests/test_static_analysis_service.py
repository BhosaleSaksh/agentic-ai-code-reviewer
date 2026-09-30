"""Unit tests for StaticAnalysisService failure isolation and concurrent orchestration."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.schemas.enums import EvidenceType
from app.schemas.static_analysis import (
    BanditResult,
    PipAuditFinding,
    PipAuditResult,
    SemgrepFinding,
    SemgrepResult,
    StaticAnalysisExecutionStatus,
)
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.bandit_runner import BanditRunner
from app.static_analysis.pip_audit_runner import PipAuditRunner
from app.static_analysis.semgrep_runner import SemgrepRunner
from app.static_analysis.service import StaticAnalysisService


@pytest.fixture
def workspace_context(tmp_path: Path) -> WorkspaceContext:
    ws_dir = tmp_path / "repo"
    ws_dir.mkdir()
    (ws_dir / "main.py").write_text("print('test')", encoding="utf-8")
    return WorkspaceContext(
        workspace_id="ws-service",
        workspace_path=ws_dir,
        repository_id=50,
        repository_full_name="org/monorepo",
        pr_number=123,
        expected_head_sha="e" * 40,
        actual_head_sha="e" * 40,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failure_isolation_semgrep_success_bandit_timeout(
    workspace_context: WorkspaceContext,
) -> None:
    """Bandit timeout must NOT erase or invalidate Semgrep's successful findings."""
    mock_semgrep = AsyncMock(spec=SemgrepRunner)
    mock_semgrep.analyzer_name = "semgrep"
    mock_semgrep.analyzer_version = "1.78.0"
    mock_semgrep.run.return_value = SemgrepResult(
        analyzer="semgrep",
        analyzer_version="1.78.0",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=0,
        duration_seconds=2.1,
        workspace_commit_sha=workspace_context.actual_head_sha,
        findings=[
            SemgrepFinding(
                rule_id="python-dangerous-eval",
                message="Dangerous eval",
                severity="ERROR",
                file_path="main.py",
                start_line=1,
                end_line=1,
            )
        ],
    )

    mock_bandit = AsyncMock(spec=BanditRunner)
    mock_bandit.analyzer_name = "bandit"
    mock_bandit.analyzer_version = "1.9.4"
    mock_bandit.run.return_value = BanditResult(
        analyzer="bandit",
        analyzer_version="1.9.4",
        execution_status=StaticAnalysisExecutionStatus.TIMEOUT,
        exit_code=None,
        duration_seconds=45.0,
        workspace_commit_sha=workspace_context.actual_head_sha,
        findings=[],
        error_message="Bandit execution timed out",
    )

    mock_pip_audit = AsyncMock(spec=PipAuditRunner)
    mock_pip_audit.analyzer_name = "pip-audit"
    mock_pip_audit.analyzer_version = "2.7.3"
    mock_pip_audit.run.return_value = PipAuditResult(
        analyzer="pip-audit",
        analyzer_version="2.7.3",
        execution_status=StaticAnalysisExecutionStatus.NOT_APPLICABLE,
        exit_code=0,
        duration_seconds=0.1,
        workspace_commit_sha=workspace_context.actual_head_sha,
        dependency_files_scanned=[],
        findings=[],
    )

    service = StaticAnalysisService(
        semgrep_runner=mock_semgrep,
        bandit_runner=mock_bandit,
        pip_audit_runner=mock_pip_audit,
    )

    summary = await service.run_all(workspace_context)

    # Verify Semgrep result was preserved intact
    assert (
        summary.semgrep.execution_status
        == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
    )
    assert len(summary.semgrep.findings) == 1
    assert summary.semgrep.findings[0].rule_id == "python-dangerous-eval"

    # Verify Bandit timeout is recorded independently without crashing
    assert summary.bandit.execution_status == StaticAnalysisExecutionStatus.TIMEOUT
    assert summary.bandit.findings == []

    # Verify pip-audit result is recorded
    assert summary.pip_audit is not None
    assert (
        summary.pip_audit.execution_status
        == StaticAnalysisExecutionStatus.NOT_APPLICABLE
    )

    # Metadata
    assert summary.workspace_commit_sha == workspace_context.actual_head_sha
    assert summary.duration_seconds >= 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failure_isolation_three_way(
    workspace_context: WorkspaceContext,
) -> None:
    """Semgrep success, Bandit timeout, pip-audit finding: all preserved independently."""
    mock_semgrep = AsyncMock(spec=SemgrepRunner)
    mock_semgrep.analyzer_name = "semgrep"
    mock_semgrep.analyzer_version = "1.78.0"
    mock_semgrep.run.return_value = SemgrepResult(
        analyzer="semgrep",
        analyzer_version="1.78.0",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=0,
        duration_seconds=1.5,
        workspace_commit_sha=workspace_context.actual_head_sha,
        findings=[
            SemgrepFinding(
                rule_id="r1",
                message="m1",
                severity="INFO",
                file_path="main.py",
                start_line=1,
                end_line=1,
            )
        ],
    )

    mock_bandit = AsyncMock(spec=BanditRunner)
    mock_bandit.analyzer_name = "bandit"
    mock_bandit.analyzer_version = "1.9.4"
    mock_bandit.run.return_value = BanditResult(
        analyzer="bandit",
        analyzer_version="1.9.4",
        execution_status=StaticAnalysisExecutionStatus.TIMEOUT,
        exit_code=None,
        duration_seconds=45.0,
        workspace_commit_sha=workspace_context.actual_head_sha,
        findings=[],
        error_message="Timed out",
    )

    mock_pip_audit = AsyncMock(spec=PipAuditRunner)
    mock_pip_audit.analyzer_name = "pip-audit"
    mock_pip_audit.analyzer_version = "2.7.3"
    mock_pip_audit.run.return_value = PipAuditResult(
        analyzer="pip-audit",
        analyzer_version="2.7.3",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=1,
        duration_seconds=2.0,
        workspace_commit_sha=workspace_context.actual_head_sha,
        dependency_files_scanned=["requirements.txt"],
        findings=[
            PipAuditFinding(
                package_name="flask",
                package_version="0.12",
                vuln_id="PYSEC-2019-1010083",
                description="Flask issue",
                fix_versions=["0.12.3"],
                aliases=["CVE-2019-1010083"],
                dependency_file="requirements.txt",
                line_number=1,
            )
        ],
    )

    service = StaticAnalysisService(
        semgrep_runner=mock_semgrep,
        bandit_runner=mock_bandit,
        pip_audit_runner=mock_pip_audit,
    )

    summary, evidence = await service.run_and_normalize(workspace_context)

    assert (
        summary.semgrep.execution_status
        == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
    )
    assert summary.bandit.execution_status == StaticAnalysisExecutionStatus.TIMEOUT
    assert summary.pip_audit is not None
    assert (
        summary.pip_audit.execution_status
        == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
    )

    # Evidence has items from Semgrep and Pip-Audit (Bandit had no findings)
    assert len(evidence) == 2
    types = [e.evidence_type for e in evidence]
    assert EvidenceType.STATIC_ANALYSIS in types
    assert EvidenceType.DEPENDENCY in types


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failure_isolation_unhandled_exception(
    workspace_context: WorkspaceContext,
) -> None:
    """An unhandled runner exception in one analyzer must be converted to EXECUTION_ERROR and not abort others."""
    mock_semgrep = AsyncMock(spec=SemgrepRunner)
    mock_semgrep.analyzer_name = "semgrep"
    mock_semgrep.analyzer_version = "1.78.0"
    mock_semgrep.run.side_effect = RuntimeError(
        "Docker daemon connection abruptly dropped"
    )

    mock_bandit = AsyncMock(spec=BanditRunner)
    mock_bandit.analyzer_name = "bandit"
    mock_bandit.analyzer_version = "1.9.4"
    mock_bandit.run.return_value = BanditResult(
        analyzer="bandit",
        analyzer_version="1.9.4",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS,
        exit_code=0,
        duration_seconds=1.0,
        workspace_commit_sha=workspace_context.actual_head_sha,
        findings=[],
    )

    mock_pip_audit = AsyncMock(spec=PipAuditRunner)
    mock_pip_audit.analyzer_name = "pip-audit"
    mock_pip_audit.analyzer_version = "2.7.3"
    mock_pip_audit.run.return_value = PipAuditResult(
        analyzer="pip-audit",
        analyzer_version="2.7.3",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS,
        exit_code=0,
        duration_seconds=0.5,
        workspace_commit_sha=workspace_context.actual_head_sha,
        dependency_files_scanned=[],
        findings=[],
    )

    service = StaticAnalysisService(
        semgrep_runner=mock_semgrep,
        bandit_runner=mock_bandit,
        pip_audit_runner=mock_pip_audit,
    )

    summary = await service.run_all(workspace_context)

    # Semgrep unhandled exception is safely caught and converted
    assert (
        summary.semgrep.execution_status
        == StaticAnalysisExecutionStatus.EXECUTION_ERROR
    )
    assert "Docker daemon connection abruptly dropped" in (
        summary.semgrep.error_message or ""
    )

    # Bandit and pip-audit succeeded cleanly
    assert (
        summary.bandit.execution_status
        == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
    )
    assert summary.pip_audit is not None
    assert (
        summary.pip_audit.execution_status
        == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
    )
