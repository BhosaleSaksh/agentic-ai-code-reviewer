"""Unit tests for SemgrepRunner using mocked container execution."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.schemas.static_analysis import StaticAnalysisExecutionStatus
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.container_runner import (
    ContainerExecutionResult,
    ContainerExecutionService,
)
from app.static_analysis.semgrep_runner import SemgrepRunner


@pytest.fixture
def workspace_context(tmp_path: Path) -> WorkspaceContext:
    ws_dir = tmp_path / "test_repo"
    ws_dir.mkdir()
    (ws_dir / "app.py").write_text("print('test')", encoding="utf-8")
    return WorkspaceContext(
        workspace_id="ws-123",
        workspace_path=ws_dir,
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=42,
        expected_head_sha="a" * 40,
        actual_head_sha="a" * 40,
    )


@pytest.mark.unit
def test_semgrep_analyzer_metadata() -> None:
    runner = SemgrepRunner()
    assert runner.analyzer_name == "semgrep"
    assert "1.78.0" in runner.analyzer_version


@pytest.mark.unit
def test_resolve_rules_priority(tmp_path: Path) -> None:
    ws = tmp_path / "repo_rules"
    ws.mkdir()
    ctx = WorkspaceContext(
        workspace_id="ws-1",
        workspace_path=ws,
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=1,
        expected_head_sha="b" * 40,
        actual_head_sha="b" * 40,
    )
    runner = SemgrepRunner()

    # 1. Default fallback
    resolved = runner._resolve_rules_path(ctx, None)
    assert resolved.name == "semgrep_default.yml"

    # 2. Workspace .semgrep.yml takes priority over default
    ws_yml = ws / ".semgrep.yml"
    ws_yml.write_text("rules: []", encoding="utf-8")
    resolved2 = runner._resolve_rules_path(ctx, None)
    assert resolved2 == ws_yml.resolve()

    # 3. Explicit custom_rules_path takes top priority
    custom = tmp_path / "custom.yml"
    custom.write_text("rules: []", encoding="utf-8")
    resolved3 = runner._resolve_rules_path(ctx, custom)
    assert resolved3 == custom.resolve()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_run_success_with_findings(
    workspace_context: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload = {
        "results": [
            {
                "check_id": "python-dangerous-eval",
                "path": "/workspace/app/vuln.py",
                "start": {"line": 10, "col": 5},
                "end": {"line": 10, "col": 20},
                "extra": {
                    "message": "Dangerous eval used",
                    "severity": "ERROR",
                    "metadata": {"cwe": "CWE-95"},
                },
            }
        ]
    }
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=0,
        duration_seconds=1.2,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    assert result.analyzer == "semgrep"
    assert (
        result.execution_status == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
    )
    assert result.exit_code == 0
    assert len(result.findings) == 1

    finding = result.findings[0]
    assert finding.rule_id == "python-dangerous-eval"
    assert finding.file_path == "app/vuln.py"
    assert finding.start_line == 10
    assert finding.end_line == 10
    assert finding.start_col == 5
    assert finding.severity == "ERROR"
    assert finding.metadata.get("cwe") == "CWE-95"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_run_success_no_findings(
    workspace_context: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload: dict[str, Any] = {"results": []}
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=0,
        duration_seconds=0.8,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    assert result.execution_status == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
    assert len(result.findings) == 0
    assert result.exit_code == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_run_timeout(workspace_context: WorkspaceContext) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="",
        stderr="Process killed",
        exit_code=None,
        duration_seconds=60.0,
        timed_out=True,
        output_limit_exceeded=False,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    assert result.execution_status == StaticAnalysisExecutionStatus.TIMEOUT
    assert result.exit_code is None
    assert "timed out" in (result.error_message or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_run_output_limit_exceeded(
    workspace_context: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="truncated...",
        stderr="",
        exit_code=None,
        duration_seconds=5.0,
        timed_out=False,
        output_limit_exceeded=True,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    assert (
        result.execution_status == StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED
    )
    assert "output exceeded limit" in (result.error_message or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_run_invalid_output(workspace_context: WorkspaceContext) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="This is definitely not JSON output",
        stderr="",
        exit_code=0,
        duration_seconds=0.5,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    assert result.execution_status == StaticAnalysisExecutionStatus.INVALID_OUTPUT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_run_execution_error_exit_code(
    workspace_context: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="",
        stderr="Fatal error: invalid configuration pattern",
        exit_code=124,
        duration_seconds=0.3,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    assert result.execution_status == StaticAnalysisExecutionStatus.EXECUTION_ERROR
    assert result.exit_code == 124


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semgrep_path_traversal_finding_dropped(
    workspace_context: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload = {
        "results": [
            {
                "check_id": "rule-traversal",
                "path": "/workspace/../../etc/passwd",
                "start": {"line": 1},
                "end": {"line": 1},
                "extra": {"message": "bad path", "severity": "ERROR"},
            },
            {
                "check_id": "rule-valid",
                "path": "/workspace/valid.py",
                "start": {"line": 5},
                "end": {"line": 5},
                "extra": {"message": "good finding", "severity": "WARNING"},
            },
        ]
    }
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=0,
        duration_seconds=1.0,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = SemgrepRunner(container_service=mock_service)
    result = await runner.run(workspace_context)

    # The traversal finding was dropped, valid finding retained
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "rule-valid"
    assert result.findings[0].file_path == "valid.py"
