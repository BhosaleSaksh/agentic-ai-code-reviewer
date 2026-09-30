"""Semgrep containerized static analysis runner for Phase 2.1.

Executes Semgrep inside an isolated, read-only Docker container with network disabled,
bounded CPU and memory, and non-root user permissions. Parses machine-readable JSON output
into strongly typed SemgrepResult and SemgrepFinding representations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.static_analysis import (
    SemgrepFinding,
    SemgrepResult,
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

# Fallback path to the bundled default Semgrep rules
_BUNDLED_DEFAULT_RULES = (
    Path(__file__).parent / "rules" / "semgrep_default.yml"
).resolve()


class SemgrepRunner(BaseStaticAnalyzer):
    """Containerized Semgrep static analysis runner."""

    def __init__(
        self,
        container_service: ContainerExecutionService | None = None,
        settings: Settings | None = None,
        default_rules_path: Path | None = None,
    ) -> None:
        super().__init__(container_service=container_service, settings=settings)
        self.default_rules_path = (
            default_rules_path
            or self.settings.SEMGREP_RULES_PATH
            or _BUNDLED_DEFAULT_RULES
        )

    @property
    def analyzer_name(self) -> str:
        return "semgrep"

    @property
    def analyzer_version(self) -> str:
        """Extract pinned version tag from SEMGREP_IMAGE (e.g. 'semgrep/semgrep:1.78.0' -> '1.78.0')."""
        image_str = self.settings.SEMGREP_IMAGE
        if ":" in image_str:
            return image_str.rsplit(":", 1)[-1]
        return "unknown"

    def _resolve_rules_path(
        self,
        workspace_context: WorkspaceContext,
        custom_rules_path: Path | None,
    ) -> Path:
        """Resolve the rules file or directory to mount for Semgrep.

        Priority:
        1. Explicit custom_rules_path if provided.
        2. Workspace-local '.semgrep.yml' if present in workspace root.
        3. Workspace-local '.semgrep' directory if present in workspace root.
        4. Application-configured default rules path (bundled semgrep_default.yml).
        """
        if custom_rules_path is not None and custom_rules_path.exists():
            return custom_rules_path.resolve()

        ws_semgrep_yml = workspace_context.workspace_path / ".semgrep.yml"
        if ws_semgrep_yml.is_file():
            return ws_semgrep_yml.resolve()

        ws_semgrep_dir = workspace_context.workspace_path / ".semgrep"
        if ws_semgrep_dir.is_dir():
            return ws_semgrep_dir.resolve()

        return self.default_rules_path.resolve()

    def _extract_json_payload(self, raw_stdout: str) -> dict[str, Any] | None:
        """Extract and parse JSON object from Semgrep stdout, ignoring surrounding text."""
        stripped = raw_stdout.strip()
        if not stripped:
            return None

        # Fast path: whole string is valid JSON
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Robust fallback: extract substring between first '{' and last '}'
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

    def _parse_findings(self, raw_results: list[Any]) -> list[SemgrepFinding]:
        """Convert raw Semgrep JSON results into strongly typed SemgrepFinding objects."""
        findings: list[SemgrepFinding] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            check_id = str(item.get("check_id") or "unknown-rule")
            raw_path = str(item.get("path") or "")

            try:
                normalized_file = self.normalize_path(raw_path)
            except PathTraversalSecurityError as exc:
                logger.warning(
                    "Dropping Semgrep finding due to path security violation: rule=%s, path=%s, error=%s",
                    check_id,
                    raw_path,
                    exc,
                )
                continue

            extra = item.get("extra", {}) if isinstance(item.get("extra"), dict) else {}
            message = str(extra.get("message") or "")
            severity = str(extra.get("severity") or "WARNING").upper()
            metadata = (
                extra.get("metadata", {})
                if isinstance(extra.get("metadata"), dict)
                else {}
            )

            start_obj = (
                item.get("start", {}) if isinstance(item.get("start"), dict) else {}
            )
            end_obj = item.get("end", {}) if isinstance(item.get("end"), dict) else {}

            try:
                start_line = max(1, int(start_obj.get("line", 1)))
                end_line = max(start_line, int(end_obj.get("line", start_line)))
            except (ValueError, TypeError):
                start_line = 1
                end_line = 1

            start_col = start_obj.get("col")
            end_col = end_obj.get("col")

            findings.append(
                SemgrepFinding(
                    rule_id=check_id,
                    message=message,
                    severity=severity,
                    file_path=normalized_file,
                    start_line=start_line,
                    end_line=end_line,
                    start_col=int(start_col) if start_col is not None else None,
                    end_col=int(end_col) if end_col is not None else None,
                    metadata=metadata,
                    raw_json=item,
                )
            )

        return findings

    async def run(
        self,
        workspace_context: WorkspaceContext,
        custom_rules_path: Path | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> SemgrepResult:
        """Execute containerized Semgrep against the verified workspace snapshot.

        Args:
            workspace_context: The verified WorkspaceContext from Phase 1.9.
            custom_rules_path: Optional path to custom Semgrep rules YAML file or directory.

        Returns:
            SemgrepResult: Structured execution result with status and findings.
        """
        self.validate_workspace(workspace_context)
        resolved_rules = self._resolve_rules_path(workspace_context, custom_rules_path)

        container_rules_target = (
            "/rules/rules.yml" if resolved_rules.is_file() else "/rules"
        )
        extra_mounts = {resolved_rules: f"{container_rules_target}:ro"}

        # Command: run Semgrep in non-git offline mode with JSON output
        command = [
            "semgrep",
            "scan",
            "--config",
            container_rules_target,
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            "--no-git-ignore",
            "--no-rewrite-rule-ids",
            "/workspace",
        ]

        config = ContainerExecutionConfig(
            image=self.settings.SEMGREP_IMAGE,
            command=command,
            workspace_path=workspace_context.workspace_path,
            container_workspace_mount="/workspace",
            read_only_mount=True,
            extra_mounts=extra_mounts,
            user=self.settings.SEMGREP_CONTAINER_USER,
            memory_limit=self.settings.STATIC_ANALYSIS_MEMORY_LIMIT,
            cpu_limit=self.settings.STATIC_ANALYSIS_CPU_LIMIT,
            network=self.settings.STATIC_ANALYSIS_NETWORK,
            timeout_seconds=self.settings.SEMGREP_TIMEOUT_SECONDS,
            max_output_bytes=self.settings.STATIC_ANALYSIS_MAX_OUTPUT_BYTES,
            environment={
                "SEMGREP_SEND_METRICS": "off",
                "SEMGREP_ENABLE_VERSION_CHECK": "0",
            },
        )

        try:
            exec_res = await self.container_service.run(config)
        except Exception as exc:
            logger.error("Failed to spawn Semgrep container: %s", exc)
            return SemgrepResult(
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

        # 1. Handle Timeout
        if exec_res.timed_out:
            return SemgrepResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.TIMEOUT,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Semgrep execution timed out after {config.timeout_seconds}s",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 2. Handle Output Limit Exceeded
        if exec_res.output_limit_exceeded:
            return SemgrepResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Semgrep output exceeded limit of {config.max_output_bytes} bytes",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 3. Parse JSON output
        parsed_json = self._extract_json_payload(exec_res.stdout)

        # Exit code semantics:
        # Semgrep exits with 0 on success.
        # Exit code 1 with valid JSON results is also treated as success with findings if --error was used.
        # Fatal crashes return 123, 124, 125, etc.
        if parsed_json is None:
            # If stdout is not valid JSON and exit code is non-zero, this is an execution error
            if exec_res.exit_code not in (0, None):
                status = StaticAnalysisExecutionStatus.EXECUTION_ERROR
                err_msg = f"Semgrep failed with exit code {exec_res.exit_code}: {exec_res.stderr[:500]}"
            else:
                status = StaticAnalysisExecutionStatus.INVALID_OUTPUT
                err_msg = "Semgrep completed but produced invalid or non-JSON output"

            return SemgrepResult(
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

        # 4. Check for fatal errors reported inside Semgrep JSON payload
        json_errors = parsed_json.get("errors", [])
        if (
            exec_res.exit_code not in (0, 1)
            and not parsed_json.get("results")
            and json_errors
        ):
            error_details = "; ".join(
                str(err.get("message", err))
                for err in json_errors
                if isinstance(err, dict)
            )
            return SemgrepResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=exec_res.exit_code,
                duration_seconds=exec_res.duration_seconds,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Semgrep reported internal errors: {error_details}",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 5. Extract findings
        raw_results = parsed_json.get("results", [])
        findings = self._parse_findings(raw_results)

        status = (
            StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
            if findings
            else StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS
        )

        return SemgrepResult(
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
