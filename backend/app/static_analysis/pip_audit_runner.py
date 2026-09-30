"""Containerized pip-audit runner for dependency vulnerability analysis.

Executes pip-audit inside an isolated, non-root, read-only Docker container to inspect
repository dependencies (e.g. requirements.txt, pyproject.toml) against known vulnerability databases.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.static_analysis import (
    PipAuditFinding,
    PipAuditResult,
    StaticAnalysisExecutionStatus,
)
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.base_runner import BaseStaticAnalyzer
from app.static_analysis.container_runner import (
    ContainerExecutionConfig,
    ContainerExecutionService,
)

logger = logging.getLogger(__name__)

# Known dependency manifest patterns supported by pip-audit
DEPENDENCY_MANIFEST_PATTERNS = [
    "requirements.txt",
    "requirements/*.txt",
    "requirements-*.txt",
    "pyproject.toml",
    "Pipfile",
    "setup.py",
]


def find_dependency_line(content: str, package_name: str) -> int | None:
    """Find the 1-indexed line number where a package is declared in a requirements file.

    Handles comments, blank lines, requirement specifiers (==, >=, <=, ~=, !=),
    and PEP 503 name normalization (hyphen vs underscore).
    """
    pkg_normalized = package_name.lower().replace("-", "_")
    for idx, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Split on standard version specifiers or environment markers
        token = re.split(r"[=><~!@;\s]", line, maxsplit=1)[0].strip()
        if token.lower().replace("-", "_") == pkg_normalized:
            return idx
    return None


class PipAuditRunner(BaseStaticAnalyzer):
    """Executes containerized pip-audit against workspace dependency manifests."""

    def __init__(
        self,
        container_service: ContainerExecutionService | None = None,
        settings: Settings | None = None,
        pinned_version: str = "2.7.3",
    ) -> None:
        super().__init__(container_service=container_service, settings=settings)
        self._pinned_version = pinned_version

    @property
    def analyzer_name(self) -> str:
        return "pip-audit"

    @property
    def analyzer_version(self) -> str:
        return self._pinned_version

    def discover_manifests(self, workspace_path: Path) -> list[Path]:
        """Discover all supported dependency manifest files within the workspace."""
        manifests: list[Path] = []

        # 1. Check requirements.txt
        req_txt = workspace_path / "requirements.txt"
        if req_txt.is_file():
            manifests.append(req_txt)

        # 2. Check requirements/*.txt
        req_dir = workspace_path / "requirements"
        if req_dir.is_dir():
            for p in sorted(req_dir.glob("*.txt")):
                if p.is_file() and p not in manifests:
                    manifests.append(p)

        # 3. Check requirements-*.txt
        for p in sorted(workspace_path.glob("requirements-*.txt")):
            if p.is_file() and p not in manifests:
                manifests.append(p)

        # 4. Check pyproject.toml
        pyproject = workspace_path / "pyproject.toml"
        if pyproject.is_file() and pyproject not in manifests:
            manifests.append(pyproject)

        # 5. Check Pipfile
        pipfile = workspace_path / "Pipfile"
        if pipfile.is_file() and pipfile not in manifests:
            manifests.append(pipfile)

        # 6. Check setup.py
        setup_py = workspace_path / "setup.py"
        if setup_py.is_file() and setup_py not in manifests:
            manifests.append(setup_py)

        return manifests

    def _build_command(
        self,
        manifest_rel_paths: list[str],
        has_requirements: bool,
    ) -> list[str]:
        """Construct deterministic CLI command arguments for pip-audit.

        Prefers auditing specific requirements files when present, or the workspace directory.
        """
        cmd: list[str] = []

        if has_requirements:
            for rel in manifest_rel_paths:
                if rel.endswith(".txt"):
                    cmd.extend(["-r", f"/workspace/{rel}"])
        else:
            # Audit workspace directory directly (e.g. pyproject.toml)
            cmd.append("/workspace")

        cmd.extend(
            [
                "-f",
                "json",
                "--desc",
                "on",
                "--aliases",
                "on",
                "--progress-spinner",
                "off",
            ]
        )
        return cmd

    def _extract_json_payload(self, stdout: str) -> dict[str, Any] | None:
        """Extract structured JSON payload from pip-audit stdout, handling diagnostic noise."""
        cleaned = stdout.strip()
        if not cleaned:
            return None

        # Direct JSON parse attempt
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Substring extraction between first '{' and last '}'
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            try:
                candidate = cleaned[start_idx : end_idx + 1]
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    def _parse_findings(
        self,
        payload: dict[str, Any],
        workspace_path: Path,
        primary_manifest_rel: str,
    ) -> list[PipAuditFinding]:
        """Parse raw JSON dependencies array into strongly typed PipAuditFinding records."""
        findings: list[PipAuditFinding] = []
        deps = payload.get("dependencies", [])

        # Cache file content for line lookup
        manifest_cache: dict[str, str] = {}
        primary_file = workspace_path / primary_manifest_rel
        if primary_file.is_file():
            with contextlib.suppress(Exception):
                manifest_cache[primary_manifest_rel] = primary_file.read_text(
                    encoding="utf-8", errors="replace"
                )

        for dep in deps:
            if not isinstance(dep, dict):
                continue
            pkg_name = dep.get("name", "unknown")
            pkg_version = dep.get("version")
            vulns = dep.get("vulns", [])

            line_no = None
            if primary_manifest_rel in manifest_cache:
                line_no = find_dependency_line(
                    manifest_cache[primary_manifest_rel], pkg_name
                )

            for vuln in vulns:
                if not isinstance(vuln, dict):
                    continue
                vuln_id = vuln.get("id", "UNKNOWN-VULN")
                desc = vuln.get("description")
                fix_versions = vuln.get("fix_versions", [])
                aliases = vuln.get("aliases", [])

                findings.append(
                    PipAuditFinding(
                        package_name=pkg_name,
                        package_version=str(pkg_version) if pkg_version else None,
                        vuln_id=vuln_id,
                        description=desc,
                        fix_versions=[str(v) for v in fix_versions],
                        aliases=[str(a) for a in aliases],
                        dependency_file=self.normalize_path(primary_manifest_rel),
                        line_number=line_no,
                        raw_json=vuln,
                    )
                )

        return findings

    async def run(
        self,
        workspace_context: WorkspaceContext,
        network_disabled: bool | None = None,
        **_kwargs: Any,
    ) -> PipAuditResult:
        """Execute containerized pip-audit against verified workspace dependencies.

        Args:
            workspace_context: Verified workspace snapshot from Phase 1.9.
            network_disabled: Override network isolation setting.
            **kwargs: Extra arguments.

        Returns:
            PipAuditResult: Strongly typed execution result.
        """
        self.validate_workspace(workspace_context)
        start_time = time.monotonic()
        workspace_path = workspace_context.workspace_path

        # 1. Discover dependency manifests
        manifests = self.discover_manifests(workspace_path)
        if not manifests:
            logger.info(
                "No dependency manifest found in workspace: repo=%s, path=%s",
                workspace_context.repository_full_name,
                workspace_path,
            )
            return PipAuditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.NOT_APPLICABLE,
                exit_code=0,
                duration_seconds=time.monotonic() - start_time,
                workspace_commit_sha=workspace_context.actual_head_sha,
                dependency_files_scanned=[],
                findings=[],
                error_message="No supported dependency manifest found in repository",
            )

        manifest_rel_paths = [
            self.normalize_path(str(m.relative_to(workspace_path))) for m in manifests
        ]
        has_requirements = any(rel.endswith(".txt") for rel in manifest_rel_paths)
        primary_manifest = manifest_rel_paths[0]

        # 2. Build command arguments
        cmd_args = self._build_command(manifest_rel_paths, has_requirements)

        # 3. Network & Cache configuration
        is_net_disabled = (
            network_disabled
            if network_disabled is not None
            else (self.settings.STATIC_ANALYSIS_NETWORK == "none")
        )

        volume_mounts: dict[Path, str] = {}
        if (
            self.settings.PIP_AUDIT_CACHE_DIR
            and self.settings.PIP_AUDIT_CACHE_DIR.is_dir()
        ):
            volume_mounts[self.settings.PIP_AUDIT_CACHE_DIR] = "/cache:ro"
            cmd_args.extend(["--cache-dir", "/cache"])

        # 4. Construct execution configuration
        timeout = getattr(
            self.settings,
            "PIP_AUDIT_TIMEOUT_SECONDS",
            self.settings.STATIC_ANALYSIS_TIMEOUT_SECONDS,
        )
        config = ContainerExecutionConfig(
            image=getattr(
                self.settings, "PIP_AUDIT_IMAGE", f"pip-audit:{self._pinned_version}"
            ),
            command=cmd_args,
            workspace_path=workspace_path,
            container_workspace_mount="/workspace",
            read_only_mount=True,
            network="none" if is_net_disabled else "bridge",
            user=getattr(self.settings, "PIP_AUDIT_CONTAINER_USER", "1000:1000"),
            memory_limit=self.settings.STATIC_ANALYSIS_MEMORY_LIMIT,
            cpu_limit=self.settings.STATIC_ANALYSIS_CPU_LIMIT,
            timeout_seconds=timeout,
            max_output_bytes=self.settings.STATIC_ANALYSIS_MAX_OUTPUT_BYTES,
            extra_mounts=volume_mounts,
        )

        logger.info(
            "Executing containerized pip-audit: repo=%s, commit=%s, manifests=%s, network_disabled=%s",
            workspace_context.repository_full_name,
            workspace_context.actual_head_sha,
            manifest_rel_paths,
            is_net_disabled,
        )

        # 5. Execute container
        exec_res = await self.container_service.run(config)
        duration = (
            exec_res.duration_seconds
            if exec_res.duration_seconds > 0.0
            else (time.monotonic() - start_time)
        )

        # 6. Handle timeouts
        if exec_res.timed_out:
            logger.warning(
                "pip-audit execution timed out after %.2fs: repo=%s",
                duration,
                workspace_context.repository_full_name,
            )
            return PipAuditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.TIMEOUT,
                exit_code=exec_res.exit_code,
                duration_seconds=duration,
                workspace_commit_sha=workspace_context.actual_head_sha,
                dependency_files_scanned=manifest_rel_paths,
                findings=[],
                error_message=f"pip-audit timed out after {timeout} seconds",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 7. Handle output limit exceeded
        if exec_res.output_limit_exceeded:
            logger.warning(
                "pip-audit exceeded max output limit: repo=%s",
                workspace_context.repository_full_name,
            )
            return PipAuditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.OUTPUT_LIMIT_EXCEEDED,
                exit_code=exec_res.exit_code,
                duration_seconds=duration,
                workspace_commit_sha=workspace_context.actual_head_sha,
                dependency_files_scanned=manifest_rel_paths,
                findings=[],
                error_message="pip-audit output exceeded maximum allowable size limit",
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 8. Parse JSON output
        payload = self._extract_json_payload(exec_res.stdout)

        if payload is None:
            if exec_res.exit_code == 0:
                logger.info(
                    "pip-audit completed with exit code 0 but produced empty output"
                )
                return PipAuditResult(
                    analyzer=self.analyzer_name,
                    analyzer_version=self.analyzer_version,
                    execution_status=StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS,
                    exit_code=0,
                    duration_seconds=duration,
                    workspace_commit_sha=workspace_context.actual_head_sha,
                    dependency_files_scanned=manifest_rel_paths,
                    findings=[],
                )

            # Execution error or invalid output
            err_msg = (
                exec_res.stderr.strip()
                if exec_res.stderr.strip()
                else f"pip-audit failed with exit code {exec_res.exit_code} and unparseable JSON"
            )
            logger.warning("pip-audit execution failed: %s", err_msg)
            return PipAuditResult(
                analyzer=self.analyzer_name,
                analyzer_version=self.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=exec_res.exit_code,
                duration_seconds=duration,
                workspace_commit_sha=workspace_context.actual_head_sha,
                dependency_files_scanned=manifest_rel_paths,
                findings=[],
                error_message=err_msg,
                raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
            )

        # 9. Extract structured findings
        findings = self._parse_findings(payload, workspace_path, primary_manifest)

        if findings:
            status = StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS
        else:
            status = StaticAnalysisExecutionStatus.SUCCESS_NO_FINDINGS

        logger.info(
            "pip-audit completed: repo=%s, status=%s, findings=%d, duration=%.2fs",
            workspace_context.repository_full_name,
            status.value,
            len(findings),
            duration,
        )

        return PipAuditResult(
            analyzer=self.analyzer_name,
            analyzer_version=self.analyzer_version,
            execution_status=status,
            exit_code=exec_res.exit_code,
            duration_seconds=duration,
            workspace_commit_sha=workspace_context.actual_head_sha,
            dependency_files_scanned=manifest_rel_paths,
            findings=findings,
            raw_stderr=exec_res.stderr[:2000] if exec_res.stderr else None,
        )
