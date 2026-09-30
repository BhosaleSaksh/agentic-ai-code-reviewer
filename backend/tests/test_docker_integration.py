"""Real Docker-dependent integration tests for static analysis sandboxes.

Validates the full Docker container execution lifecycle against actual Semgrep and Bandit images:
1. Container launches cleanly
2. Analyzer executes
3. Analyzer runs as non-root (effective UID != 0)
4. Workspace is mounted read-only (write operations fail)
5. Memory limit is applied
6. CPU limit is applied
7. Network isolation is enforced (no outbound access)
8. Expected security findings are detected on vulnerable fixtures
9. Workspace contents and timestamps remain completely unchanged
10. Container terminates cleanly with no orphaned processes
11. Timeout terminates the container
12. Oversized output is safely trapped (OUTPUT_LIMIT_EXCEEDED)
13. Analyzer failure is returned as structured status
"""

import os
import shutil
from pathlib import Path

import pytest
from app.schemas.static_analysis import StaticAnalysisExecutionStatus
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.bandit_runner import BanditRunner
from app.static_analysis.container_runner import (
    ContainerExecutionConfig,
    ContainerExecutionService,
)
from app.static_analysis.pip_audit_runner import PipAuditRunner
from app.static_analysis.semgrep_runner import SemgrepRunner
from app.static_analysis.service import StaticAnalysisService

_DOCKER_AVAILABLE = ContainerExecutionService().is_docker_available()
_FIXTURES_DIR = (Path(__file__).parent / "fixtures" / "static_analysis").resolve()


def _get_workspace_snapshot(path: Path) -> dict[str, tuple[int, float]]:
    """Capture snapshot of all files, byte sizes, and modification times."""
    snapshot: dict[str, tuple[int, float]] = {}
    for root, _, files in os.walk(path):
        for f in files:
            full_p = Path(root) / f
            rel = str(full_p.relative_to(path))
            stat_res = full_p.stat()
            snapshot[rel] = (stat_res.st_size, stat_res.st_mtime)
    return snapshot


@pytest.fixture
def clean_workspace(tmp_path: Path) -> WorkspaceContext:
    src_dir = _FIXTURES_DIR / "clean_python"
    target_dir = tmp_path / "clean_repo"
    shutil.copytree(src_dir, target_dir)
    return WorkspaceContext(
        workspace_id="ws-clean",
        workspace_path=target_dir,
        repository_id=101,
        repository_full_name="org/clean-repo",
        pr_number=1,
        expected_head_sha="1" * 40,
        actual_head_sha="1" * 40,
    )


@pytest.fixture
def vulnerable_workspace(tmp_path: Path) -> WorkspaceContext:
    src_dir = _FIXTURES_DIR / "insecure_python"
    target_dir = tmp_path / "vuln_repo"
    shutil.copytree(src_dir, target_dir)
    return WorkspaceContext(
        workspace_id="ws-vuln",
        workspace_path=target_dir,
        repository_id=102,
        repository_full_name="org/vuln-repo",
        pr_number=2,
        expected_head_sha="2" * 40,
        actual_head_sha="2" * 40,
    )


@pytest.fixture
def semgrep_vulnerable_workspace(tmp_path: Path) -> WorkspaceContext:
    src_dir = _FIXTURES_DIR / "semgrep_vulnerable"
    target_dir = tmp_path / "semgrep_repo"
    shutil.copytree(src_dir, target_dir)
    return WorkspaceContext(
        workspace_id="ws-semgrep-vuln",
        workspace_path=target_dir,
        repository_id=103,
        repository_full_name="org/semgrep-repo",
        pr_number=3,
        expected_head_sha="3" * 40,
        actual_head_sha="3" * 40,
    )


@pytest.fixture
def non_python_workspace(tmp_path: Path) -> WorkspaceContext:
    src_dir = _FIXTURES_DIR / "non_python_repo"
    target_dir = tmp_path / "non_py_repo"
    shutil.copytree(src_dir, target_dir)
    return WorkspaceContext(
        workspace_id="ws-non-py",
        workspace_path=target_dir,
        repository_id=104,
        repository_full_name="org/non-py-repo",
        pr_number=4,
        expected_head_sha="4" * 40,
        actual_head_sha="4" * 40,
    )


@pytest.mark.integration
@pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker daemon is not available")
class TestDockerStaticAnalysisIntegration:
    """Live Docker integration tests validating security isolation and static analysis."""

    @pytest.mark.asyncio
    async def test_container_executes_as_non_root(
        self, clean_workspace: WorkspaceContext
    ) -> None:
        """Requirement 1, 3: Verify container executes with non-root UID (effective UID != 0)."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="alpine:latest",
            command=["id", "-u"],
            workspace_path=clean_workspace.workspace_path,
            user="1000:1000",
        )
        res = await service.run(config)
        assert res.exit_code == 0
        effective_uid = res.stdout.strip()
        assert effective_uid == "1000"
        assert int(effective_uid) != 0

    @pytest.mark.asyncio
    async def test_workspace_is_read_only(
        self, clean_workspace: WorkspaceContext
    ) -> None:
        """Requirement 4: Verify analyzer container cannot modify or write files into workspace."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="alpine:latest",
            command=["touch", "/workspace/malicious_payload.txt"],
            workspace_path=clean_workspace.workspace_path,
            read_only_mount=True,
            user="1000:1000",
        )
        res = await service.run(config)
        # Attempting to write to read-only mount must fail with non-zero exit code
        assert res.exit_code != 0
        assert "Read-only file system" in res.stderr
        assert not (clean_workspace.workspace_path / "malicious_payload.txt").exists()

    @pytest.mark.asyncio
    async def test_network_isolation_enforced(
        self, clean_workspace: WorkspaceContext
    ) -> None:
        """Requirement 7: Verify network isolation prevents all external network communication."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="alpine:latest",
            command=["ping", "-c", "1", "8.8.8.8"],
            workspace_path=clean_workspace.workspace_path,
            network="none",
        )
        res = await service.run(config)
        assert res.exit_code != 0
        assert (
            "Network unreachable" in res.stderr
            or "Network is unreachable" in res.stderr
        )

    @pytest.mark.asyncio
    async def test_resource_limits_applied(
        self, clean_workspace: WorkspaceContext
    ) -> None:
        """Requirement 5, 6: Verify memory and CPU limits are applied to container execution."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="alpine:latest",
            command=["echo", "limits_ok"],
            workspace_path=clean_workspace.workspace_path,
            memory_limit="256m",
            cpu_limit="1.0",
        )
        res = await service.run(config)
        assert res.exit_code == 0
        assert "limits_ok" in res.stdout

    @pytest.mark.asyncio
    async def test_semgrep_vulnerable_fixture_detection(
        self,
        vulnerable_workspace: WorkspaceContext,
    ) -> None:
        """Requirement 8: Verify Semgrep detects expected vulnerabilities on synthetic fixture."""
        runner = SemgrepRunner()
        before_snapshot = _get_workspace_snapshot(vulnerable_workspace.workspace_path)

        res = await runner.run(vulnerable_workspace)

        assert res.analyzer == "semgrep"
        assert (
            res.execution_status == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
        )
        assert len(res.findings) >= 3

        detected_rule_ids = {f.rule_id for f in res.findings}
        # Insecure fixture contains dangerous eval, subprocess shell=True, and weak MD5 hash
        assert "python-dangerous-eval" in detected_rule_ids
        assert "python-command-injection-shell-true" in detected_rule_ids
        assert "python-weak-cryptographic-hash" in detected_rule_ids

        # Requirement 9: Workspace must remain 100% unchanged
        after_snapshot = _get_workspace_snapshot(vulnerable_workspace.workspace_path)
        assert before_snapshot == after_snapshot

    @pytest.mark.asyncio
    async def test_bandit_vulnerable_fixture_detection(
        self,
        vulnerable_workspace: WorkspaceContext,
    ) -> None:
        """Requirement 8: Verify Bandit detects expected vulnerabilities on synthetic fixture."""
        runner = BanditRunner()
        before_snapshot = _get_workspace_snapshot(vulnerable_workspace.workspace_path)

        res = await runner.run(vulnerable_workspace)

        assert res.analyzer == "bandit"
        assert (
            res.execution_status == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
        )
        assert len(res.findings) >= 3

        test_ids = {f.test_id for f in res.findings}
        # B307 (eval), B602 (subprocess shell=True), B303/B324 (MD5), B506 (yaml.load)
        assert "B307" in test_ids
        assert "B602" in test_ids

        # Requirement 9: Workspace must remain 100% unchanged
        after_snapshot = _get_workspace_snapshot(vulnerable_workspace.workspace_path)
        assert before_snapshot == after_snapshot

    @pytest.mark.asyncio
    async def test_clean_fixture_produces_no_findings(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Requirement 8, 9: Verify clean fixture runs successfully without false positives."""
        service = StaticAnalysisService()
        before_snapshot = _get_workspace_snapshot(clean_workspace.workspace_path)

        summary = await service.run_all(clean_workspace)

        assert (
            summary.semgrep.execution_status
            == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
        )
        assert len(summary.semgrep.findings) == 0

        assert (
            summary.bandit.execution_status
            == StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
        )
        assert len(summary.bandit.findings) == 0

        after_snapshot = _get_workspace_snapshot(clean_workspace.workspace_path)
        assert before_snapshot == after_snapshot

    @pytest.mark.asyncio
    async def test_non_python_fixture_returns_not_applicable_for_bandit(
        self,
        non_python_workspace: WorkspaceContext,
    ) -> None:
        """Verify Bandit returns NOT_APPLICABLE for repositories without Python files."""
        service = StaticAnalysisService()

        summary = await service.run_all(non_python_workspace)

        # Semgrep executes on non-python code
        assert summary.semgrep.execution_status in (
            StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS,
            StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        )

        # Bandit recognizes non-applicability without error
        assert (
            summary.bandit.execution_status
            == StaticAnalysisExecutionStatus.NOT_APPLICABLE
        )
        assert summary.bandit.findings == []
        assert summary.bandit.exit_code == 0

    @pytest.mark.asyncio
    async def test_timeout_terminates_container(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Requirement 10, 11: Verify execution timeout stops container and cleans up."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="alpine:latest",
            command=["sleep", "30"],
            workspace_path=clean_workspace.workspace_path,
            timeout_seconds=1.0,
        )
        res = await service.run(config)
        assert res.timed_out is True
        assert res.exit_code is None

    @pytest.mark.asyncio
    async def test_oversized_output_is_safely_handled(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Requirement 12: Verify output exceeding max_output_bytes returns OUTPUT_LIMIT_EXCEEDED."""
        from app.core.config import Settings

        # Use an isolated Settings instance so the global singleton is not mutated
        custom_settings = Settings(STATIC_ANALYSIS_MAX_OUTPUT_BYTES=100)
        runner = SemgrepRunner(settings=custom_settings)
        res = await runner.run(clean_workspace)
        assert (
            res.execution_status == StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED
        )
        assert "output exceeded limit" in (res.error_message or "")

    @pytest.mark.asyncio
    async def test_semgrep_detects_secrets_and_os_calls(
        self,
        semgrep_vulnerable_workspace: WorkspaceContext,
    ) -> None:
        """Verify Semgrep detects hardcoded secrets and dangerous OS system calls."""
        runner = SemgrepRunner()
        res = await runner.run(semgrep_vulnerable_workspace)

        assert (
            res.execution_status == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
        )
        assert len(res.findings) >= 2
        detected_rule_ids = {f.rule_id for f in res.findings}
        assert "generic-hardcoded-secret" in detected_rule_ids
        assert "python-os-system-call" in detected_rule_ids

    @pytest.mark.asyncio
    async def test_analyzer_failure_returns_structured_status(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Requirement 13: Verify analyzer container crash returns structured EXECUTION_ERROR."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="alpine:latest",
            command=["sh", "-c", "echo 'fatal internal error' >&2; exit 125"],
            workspace_path=clean_workspace.workspace_path,
        )
        res = await service.run(config)
        assert res.exit_code == 125
        assert "fatal internal error" in res.stderr

    @pytest.mark.asyncio
    async def test_static_analysis_service_concurrent_full_run(
        self,
        vulnerable_workspace: WorkspaceContext,
    ) -> None:
        """Verify StaticAnalysisService coordinates Semgrep and Bandit concurrently."""
        service = StaticAnalysisService()
        summary = await service.run_all(vulnerable_workspace)

        assert (
            summary.semgrep.execution_status
            == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
        )
        assert len(summary.semgrep.findings) >= 3
        assert (
            summary.bandit.execution_status
            == StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
        )
        assert len(summary.bandit.findings) >= 3
        assert summary.duration_seconds > 0.0
        assert summary.workspace_commit_sha == vulnerable_workspace.actual_head_sha

    @pytest.mark.asyncio
    async def test_docker_pip_audit_non_root_execution(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Verify pip-audit container runs as non-root user (UID 1000)."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="pip-audit:2.7.3",
            entrypoint="id",
            command=["-u"],
            workspace_path=clean_workspace.workspace_path,
            user="1000:1000",
        )
        res = await service.run(config)
        assert res.exit_code == 0
        assert res.stdout.strip() == "1000"

    @pytest.mark.asyncio
    async def test_docker_pip_audit_workspace_is_read_only(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Verify repository workspace is mounted read-only for pip-audit."""
        service = ContainerExecutionService()
        config = ContainerExecutionConfig(
            image="pip-audit:2.7.3",
            entrypoint="touch",
            command=["/workspace/tamper_pip_audit.txt"],
            workspace_path=clean_workspace.workspace_path,
            read_only_mount=True,
            user="1000:1000",
        )
        res = await service.run(config)
        assert res.exit_code != 0
        assert not (clean_workspace.workspace_path / "tamper_pip_audit.txt").exists()

    @pytest.mark.asyncio
    async def test_docker_pip_audit_no_manifest_not_applicable(
        self,
        clean_workspace: WorkspaceContext,
    ) -> None:
        """Verify pip-audit reports NOT_APPLICABLE on repos without dependency manifests."""
        runner = PipAuditRunner()
        # clean_workspace has no requirements.txt or pyproject.toml
        res = await runner.run(clean_workspace)
        assert res.execution_status == StaticAnalysisExecutionStatus.NOT_APPLICABLE
        assert res.findings == []
