"""Bandit containerized static analysis runner for Phase 2.1.

Executes Bandit inside an isolated, read-only Docker container with network disabled,
bounded CPU and memory, and non-root user permissions. Parses machine-readable JSON output
into strongly typed BanditResult and BanditFinding representations.
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.static_analysis import (
    BanditFinding,
    BanditResult,
    StaticAnalysisExecutionStatus,
)
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.base_runner import BaseStaticAnalyzer
from app.static_analysis.container_runner import (
    ContainerExecutionConfig,
    ContainerExecutionService,
)
from app.static_analysis.path_utils import PathTraversalSecurityError

logger = logging.getLogger(__name__)


class BanditRunner(BaseStaticAnalyzer):
    """Containerized Bandit static analysis runner for Python code."""

    def __init__(
        self,
        container_service: ContainerExecutionService | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(container_service=container_service, settings=settings)

    @property
    def analyzer_name(self) -> str:
        return "bandit"

    @property
    def analyzer_version(self) -> str:
        """Extract pinned version tag from BANDIT_IMAGE (e.g. 'ghcr.io/pycqa/bandit/bandit:1.9.4' -> '1.9.4')."""
        image_str = self.settings.BANDIT_IMAGE
        if ":" in image_str:
            return image_str.rsplit(":", 1)[-1]
        return "unknown"

    def has_python_files(self, workspace_path: Path) -> bool:
        """Check if workspace contains at least one Python (.py) file."""
        try:
            for item in workspace_path.rglob("*.py"):
                if item.is_file():
                    return True
        except Exception as exc:
            logger.debug(
                "Error checking for python files in %s: %s", workspace_path, exc
            )
        return False

    def _extract_json_payload(self, raw_stdout: str) -> dict[str, Any] | None:
        """Extract and parse JSON object from Bandit stdout, ignoring surrounding text."""
        stripped = raw_stdout.strip()
        if not stripped:
            return None

        # Fast path
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Substring fallback
        start_idx = stripped.find("{")
        end_idx = stripped.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = stripped[start_idx : end_idx + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    def _parse_findings(self, raw_results: list[Any]) -> list[BanditFinding]:
        """Convert raw Bandit JSON results into strongly typed BanditFinding objects."""
        findings: list[BanditFinding] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            test_id = str(item.get("test_id") or "B000")
            test_name = str(item.get("test_name") or "unknown_test")
            issue_text = str(item.get("issue_text") or "")
            severity = str(item.get("issue_severity") or "LOW").upper()
            confidence = str(item.get("issue_confidence") or "LOW").upper()
            raw_path = str(item.get("filename") or "")

            try:
                normalized_file = self.normalize_path(raw_path)
            except PathTraversalSecurityError as exc:
                logger.warning(
                    "Dropping Bandit finding due to path security violation: test_id=%s, path=%s, error=%s",
                    test_id,
                    raw_path,
                    exc,
                )
                continue

            try:
                line_number = max(1, int(item.get("line_number", 1)))
            except (ValueError, TypeError):
                line_number = 1

            raw_range = item.get("line_range", [])
            line_range: list[int] = []
            if isinstance(raw_range, list):
                for val in raw_range:
                    with contextlib.suppress(ValueError, TypeError):
                        line_range.append(int(val))

            code = item.get("code")
            code_str = str(code) if code is not None else None
            more_info = item.get("more_info")
            more_info_str = str(more_info) if more_info is not None else None

            findings.append(
                BanditFinding(
                    test_id=test_id,
                    test_name=test_name,
                    issue_text=issue_text,
                    severity=severity,
                    confidence=confidence,
                    file_path=normalized_file,
                    line_number=line_number,
                    line_range=line_range,
                    code=code_str,
                    more_info=more_info_str,
                    raw_json=item,
                )
            )

        return findings

    async def run(
        self,
        workspace_context: WorkspaceContext,
        **kwargs: Any,  # noqa: ARG002
    ) -> BanditResult:
        """Execute containerized Bandit against the verified workspace snapshot.

        If the repository workspace contains no Python files, Bandit execution is skipped
        and a NOT_APPLICABLE status is returned immediately.

        Args:
            workspace_context: The verified WorkspaceContext from Phase 1.9.

        Returns:
            BanditResult: Structured execution result with status and findings.
        """
        self.validate_workspace(workspace_context)

        # 1. Applicability check: if no Python files are in the repository, return NOT_APPLICABLE
        if not self.has_python_files(workspace_context.workspace_path):
            logger.info(
                "Bandit skipped: no Python files found in workspace for %s (commit %s)",
                workspace_context.repository_full_name,
                workspace_context.actual_head_sha,
            )
            return BanditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.NOT_APPLICABLE,
                exit_code=0,
                duration_seconds=0.0,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=None,
                raw_stderr=None,
            )

        # 2. Command: recursive scan of /workspace, output JSON to stdout
        command = [
            "-f",
            "json",
            "-r",
            "/workspace",
        ]

        config = ContainerExecutionConfig(
            image=self.settings.BANDIT_IMAGE,
            command=command,
            workspace_path=workspace_context.workspace_path,
            container_workspace_mount="/workspace",
            read_only_mount=True,
            user=self.settings.BANDIT_CONTAINER_USER,
            memory_limit=self.settings.STATIC_ANALYSIS_MEMORY_LIMIT,
            cpu_limit=self.settings.STATIC_ANALYSIS_CPU_LIMIT,
            network=self.settings.STATIC_ANALYSIS_NETWORK,
            timeout_seconds=self.settings.BANDIT_TIMEOUT_SECONDS,
            max_output_bytes=self.settings.STATIC_ANALYSIS_MAX_OUTPUT_BYTES,
        )

        try:
            exec_res = await self.container_service.run(config)
        except Exception as exc:
            logger.error("Failed to spawn Bandit container: %s", exc)
            return BanditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=None,
                duration_seconds=0.0,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Failed to execute container: {exc}",
                raw_stderr=str(exc),
            )

        # 3. Handle Timeout
        if exec_res.timed_out:
            return BanditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.TIMEOUT,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Bandit execution timed out after {config.timeout_seconds}s",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 4. Handle Output Limit Exceeded
        if exec_res.output_limit_exceeded:
            return BanditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Bandit output exceeded limit of {config.max_output_bytes} bytes",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 5. Parse JSON output
        parsed_json = self._extract_json_payload(exec_res.stdout)

        # Exit code semantics for Bandit:
        # Exit code 0: No issues found
        # Exit code 1: Issues found (normal completion with findings, NOT an execution error!)
        # Exit code 2: Command-line or parsing crash
        if parsed_json is None:
            if exec_res.exit_code not in (0, 1, None):
                status = StaticAnalysisExecutionStatus.EXECUTION_ERROR
                err_msg = f"Bandit failed with exit code {exec_res.exit_code}: {exec_res.stderr[:500]}"
            else:
                status = StaticAnalysisExecutionStatus.INVALID_OUTPUT
                err_msg = "Bandit completed but produced invalid or non-JSON output"

            return BanditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=status,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=err_msg,
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        if exec_res.exit_code == 2:
            return BanditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Bandit reported fatal error (exit code 2): {exec_res.stderr[:500]}",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 6. Extract findings
        raw_results = parsed_json.get("results", [])
        findings = self._parse_findings(raw_results)

        status = (
            StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
            if findings
            else StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
        )

        return BanditResult(
            analyzer=self.analyzer_name,
            analyzer_version=self.analyzer_version,
            execution_status=status,
            exit_code=exec_res.exit_code,
            duration_seconds=exec_res.duration_seconds,
            workspace_commit_sha=workspace_context.actual_head_sha,
            findings=findings,
            error_message=None,
            raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
        )
