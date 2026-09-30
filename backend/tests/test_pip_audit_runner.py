"""Unit tests for PipAuditRunner using mocked container execution."""

from __future__ import annotations

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
from app.static_analysis.pip_audit_runner import PipAuditRunner, find_dependency_line


@pytest.fixture
def workspace_with_requirements(tmp_path: Path) -> WorkspaceContext:
    ws_dir = tmp_path / "req_repo"
    ws_dir.mkdir()
    req_file = ws_dir / "requirements.txt"
    req_file.write_text(
        "# Project dependencies\nrequests==2.28.1\nflask==0.12\n",
        encoding="utf-8",
    )
    return WorkspaceContext(
        workspace_id="ws-req",
        workspace_path=ws_dir,
        repository_id=101,
        repository_full_name="org/req-repo",
        pr_number=1,
        expected_head_sha="a" * 40,
        actual_head_sha="a" * 40,
    )


@pytest.fixture
def workspace_without_manifest(tmp_path: Path) -> WorkspaceContext:
    ws_dir = tmp_path / "empty_repo"
    ws_dir.mkdir()
    (ws_dir / "app.py").write_text("print('hello')", encoding="utf-8")
    return WorkspaceContext(
        workspace_id="ws-no-manifest",
        workspace_path=ws_dir,
        repository_id=102,
        repository_full_name="org/no-manifest-repo",
        pr_number=2,
        expected_head_sha="b" * 40,
        actual_head_sha="b" * 40,
    )


@pytest.mark.unit
def test_find_dependency_line() -> None:
    content = """# Comment line
--extra-index-url https://example.com/pypi

urllib3>=1.26.0
flask==0.12 ; python_version > '3.7'
jinja2-time~=0.2.0
"""
    assert find_dependency_line(content, "urllib3") == 4
    assert find_dependency_line(content, "flask") == 5
    # Test normalization: jinja2_time matches jinja2-time
    assert find_dependency_line(content, "jinja2_time") == 6
    assert find_dependency_line(content, "nonexistent") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_not_applicable_when_no_manifest(
    workspace_without_manifest: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    runner = PipAuditRunner(container_service=mock_service)

    result = await runner.run(workspace_without_manifest)

    assert result.execution_status == StaticAnalysisExecutionStatus.NOT_APPLICABLE
    assert result.findings == []
    assert result.dependency_files_scanned == []
    mock_service.run.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_success_no_findings(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload: dict[str, Any] = {"dependencies": [], "fixes": []}
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="",
        exit_code=0,
        duration_seconds=1.2,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert result.execution_status == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
    assert len(result.findings) == 0
    assert result.exit_code == 0
    assert result.duration_seconds == 1.2
    assert "requirements.txt" in result.dependency_files_scanned


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_success_with_findings_exit_code_1(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    payload = {
        "dependencies": [
            {
                "name": "flask",
                "version": "0.12",
                "vulns": [
                    {
                        "id": "PYSEC-2019-1010083",
                        "description": "Flask before 0.12.3 contains an unexpected memory use vulnerability.",
                        "fix_versions": ["0.12.3"],
                        "aliases": ["CVE-2019-1010083"],
                    }
                ],
            }
        ]
    }
    # pip-audit returns exit_code=1 when findings are present
    mock_service.run.return_value = ContainerExecutionResult(
        stdout=json.dumps(payload),
        stderr="1 known vulnerability found",
        exit_code=1,
        duration_seconds=2.1,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert (
        result.execution_status == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
    )
    assert len(result.findings) == 1
    assert result.exit_code == 1

    finding = result.findings[0]
    assert finding.package_name == "flask"
    assert finding.package_version == "0.12"
    assert finding.vuln_id == "PYSEC-2019-1010083"
    assert finding.aliases == ["CVE-2019-1010083"]
    assert finding.fix_versions == ["0.12.3"]
    assert finding.dependency_file == "requirements.txt"
    assert finding.line_number == 3  # flask==0.12 is on line 3 in fixture


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_execution_error_exit_code_1_no_json(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="",
        stderr="ConnectionError: Network is unreachable",
        exit_code=1,
        duration_seconds=0.5,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert result.execution_status == StaticAnalysisExecutionStatus.EXECUTION_ERROR
    assert result.exit_code == 1
    assert result.findings == []
    assert "ConnectionError" in str(result.error_message)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_execution_error_exit_code_2(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="usage error",
        stderr="pip-audit: error: unrecognized arguments",
        exit_code=2,
        duration_seconds=0.2,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert result.execution_status == StaticAnalysisExecutionStatus.EXECUTION_ERROR
    assert result.exit_code == 2
    assert result.findings == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_timeout(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="",
        stderr="Process killed by timeout",
        exit_code=None,
        duration_seconds=60.0,
        timed_out=True,
        output_limit_exceeded=False,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert result.execution_status == StaticAnalysisExecutionStatus.TIMEOUT
    assert result.findings == []
    assert result.duration_seconds == 60.0
    assert "timed out" in str(result.error_message).lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_output_limit_exceeded(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="[truncated output...]",
        stderr="",
        exit_code=None,
        duration_seconds=1.5,
        timed_out=False,
        output_limit_exceeded=True,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert (
        result.execution_status == StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED
    )
    assert result.findings == []
    assert "maximum allowable size limit" in str(result.error_message)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pip_audit_run_malformed_json_with_diagnostic(
    workspace_with_requirements: WorkspaceContext,
) -> None:
    mock_service = AsyncMock(spec=ContainerExecutionService)
    mock_service.run.return_value = ContainerExecutionResult(
        stdout="{ broken json ...",
        stderr="Unexpected error encountered",
        exit_code=1,
        duration_seconds=0.8,
        timed_out=False,
        output_limit_exceeded=False,
    )

    runner = PipAuditRunner(container_service=mock_service)
    result = await runner.run(workspace_with_requirements)

    assert result.execution_status == StaticAnalysisExecutionStatus.EXECUTION_ERROR
    assert result.findings == []


@pytest.mark.unit
def test_pip_audit_manifest_discovery_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("pkg1==1.0", encoding="utf-8")
    req_dir = repo / "requirements"
    req_dir.mkdir()
    (req_dir / "prod.txt").write_text("pkg2==2.0", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]", encoding="utf-8")

    runner = PipAuditRunner()
    manifests = runner.discover_manifests(repo)

    names = [m.name for m in manifests]
    assert "requirements.txt" in names
    assert "prod.txt" in names
    assert "pyproject.toml" in names
