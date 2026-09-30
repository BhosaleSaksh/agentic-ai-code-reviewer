"""Unit tests for BanditRunner using mocked container execution."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.schemas.static_analysis import StaticAnalysisExecutionStatus
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.bandit_runner import BanditRunner
from app.static_analysis.container_runner import (
    ContainerExecutionResult,
    ContainerExecutionService,
)


@pytest.fixture
def workspace_with_python(tmp_path: Path) -> WorkspaceContext:
    ws_dir = tmp_path / "python_repo"
    ws_dir.mkdir()
    (ws_dir / "service.py").write_text("print('hello')", encoding="utf-8")
    return WorkspaceContext(
        workspace_id="ws-py",
        workspace_path=ws_dir,
        repository_id=10,
        repository_full_name="org/py-repo",
        pr_number=5,
        expected_head_sha="c" * 40,
        actual_head_sha="c" * 40,
    )


@pytest.fixture
def workspace_without_python(tmp_path: Path) -> WorkspaceContext:
    ws_dir = tmp_path / "non_python_repo"
    ws_dir.mkdir()
    (ws_dir / "index.js").write_text("console.log('hi')", encoding="utf-8")
    (ws_dir / "README.md").write_text("# Doc", encoding="utf-8")
    return WorkspaceContext(
        workspace_id="ws-no-py",
        workspace_path=ws_dir,
        repository_id=20,
        repository_full_name="org/js-repo",
        pr_number=10,
        expected_head_sha="d" * 40,
        actual_head_sha="d" * 40,
    )


@pytest.mark.unit
def test_bandit_analyzer_metadata() -> None:
    runner = BanditRunner()
    assert runner.analyzer_name == "bandit"
    assert "1.9.4" in runner.analyzer_version


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_not_applicable_when_no_python_files(
    workspace_without_python: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    runner = BanditRunner(container_service=mock_service)

    result = await runner.run(workspace_without_python)

    assert result.analyzer == "bandit"
    assert result.execution_status == StaticAnalysisExecutionStatus.NOT_APPLICABLE
    assert result.findings == []
    assert result.duration_seconds == 0.0
    # Crucial: container must NOT be spawned when repo has no Python files
    mock_service.run.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_run_success_with_findings_exit_code_1(
    workspace_with_python: WorkspaceContext,
) -> None:
    # Bandit exits with 1 when vulnerabilities are identified
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload = {
        "results": [
            {
                "code": "1 eval('x + 1')\n",
                "filename": "/workspace/service.py",
                "issue_confidence": "HIGH",
                "issue_severity": "MEDIUM",
                "issue_text": "Use of possibly insecure function",
                "line_number": 1,
                "line_range": [1],
                "more_info": "https://bandit.readthedocs.io/en/latest/",
                "test_id": "B307",
                "test_name": "eval",
            }
        ]
    }
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=1,  # Bandit standard exit code on findings
        duration_seconds=1.5,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = BanditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_python)

    assert (
        result.execution_status == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
    )
    assert result.exit_code == 1
    assert len(result.findings) == 1

    finding = result.findings[0]
    assert finding.test_id == "B307"
    assert finding.test_name == "eval"
    assert finding.file_path == "service.py"
    assert finding.line_number == 1
    assert finding.line_range == [1]
    assert finding.severity == "MEDIUM"
    assert finding.confidence == "HIGH"
    assert "eval" in (finding.code or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_run_success_no_findings_exit_code_0(
    workspace_with_python: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload: dict[str, Any] = {"results": []}
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=0,
        duration_seconds=0.9,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = BanditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_python)

    assert result.execution_status == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
    assert result.exit_code == 0
    assert len(result.findings) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_run_fatal_crash_exit_code_2(
    workspace_with_python: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="",
        stderr="Bandit execution error: unable to parse syntax",
        exit_code=2,
        duration_seconds=0.4,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = BanditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_python)

    assert result.execution_status == StaticAnalysisExecutionStatus.EXECUTION_ERROR
    assert result.exit_code == 2
    assert "exit code 2" in (result.error_message or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_run_timeout(
    workspace_with_python: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="",
        stderr="",
        exit_code=None,
        duration_seconds=45.0,
        timed_out=True,
        output_limit_exceeded=False,
    )

    runner = BanditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_python)

    assert result.execution_status == StaticAnalysisExecutionStatus.TIMEOUT
    assert result.exit_code is None
    assert "timed out" in (result.error_message or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_run_output_limit_exceeded(
    workspace_with_python: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="huge output...",
        stderr="",
        exit_code=None,
        duration_seconds=3.0,
        timed_out=False,
        output_limit_exceeded=True,
    )

    runner = BanditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_python)

    assert (
        result.execution_status == StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED
    )
    assert "output exceeded limit" in (result.error_message or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bandit_path_traversal_dropped(
    workspace_with_python: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload = {
        "results": [
            {
                "code": "eval()",
                "filename": "/workspace/../../etc/passwd",
                "issue_confidence": "HIGH",
                "issue_severity": "HIGH",
                "issue_text": "Dangerous",
                "line_number": 1,
                "test_id": "B307",
                "test_name": "eval",
            },
            {
                "code": "assert True",
                "filename": "/workspace/service.py",
                "issue_confidence": "HIGH",
                "issue_severity": "LOW",
                "issue_text": "Assert used",
                "line_number": 20,
                "test_id": "B101",
                "test_name": "assert_used",
            },
        ]
    }
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=1,
        duration_seconds=1.0,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = BanditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_python)

    assert len(result.findings) == 1
    assert result.findings[0].test_id == "B101"
    assert result.findings[0].file_path == "service.py"
