"""Static analysis orchestration service for Phase 2.1 & Phase 2.2.

Coordinates concurrent execution of containerized Semgrep, Bandit, and pip-audit analyzers
against a verified WorkspaceContext snapshot, guaranteeing independent failure isolation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.evidence import EvidenceModel
from app.schemas.static_analysis import (
    BanditResult,
    PipAuditResult,
    SemgrepResult,
    StaticAnalysisExecutionStatus,
    ToolAnalysisSummary,
)
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.bandit_runner import BanditRunner
from app.static_analysis.container_runner import ContainerExecutionService
from app.static_analysis.evidence_normalizer import normalize_tool_analysis_summary
from app.static_analysis.pip_audit_runner import PipAuditRunner
from app.static_analysis.semgrep_runner import SemgrepRunner

logger = logging.getLogger(__name__)


class StaticAnalysisService:
    """Orchestrator for containerized static analysis tools."""

    def __init__(
        self,
        semgrep_runner: SemgrepRunner | None = None,
        bandit_runner: BanditRunner | None = None,
        pip_audit_runner: PipAuditRunner | None = None,
        container_service: ContainerExecutionService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        shared_container_service = container_service or ContainerExecutionService()

        self.semgrep = semgrep_runner or SemgrepRunner(
            container_service=shared_container_service,
            settings=self.settings,
        )
        self.bandit = bandit_runner or BanditRunner(
            container_service=shared_container_service,
            settings=self.settings,
        )
        self.pip_audit = pip_audit_runner or PipAuditRunner(
            container_service=shared_container_service,
            settings=self.settings,
        )

    def is_docker_available(self) -> bool:
        """Check whether Docker is available for container execution."""
        return self.semgrep.container_service.is_docker_available()

    async def run_all(
        self,
        workspace_context: WorkspaceContext,
        semgrep_rules_path: Any | None = None,
        pip_audit_network_disabled: bool | None = None,
    ) -> ToolAnalysisSummary:
        """Execute Semgrep, Bandit, and pip-audit concurrently with strict failure isolation.

        Ensures that an execution error, timeout, or crash in one tool does not affect
        or invalidate the results produced by the other tools.

        Args:
            workspace_context: Verified workspace snapshot from Phase 1.9.
            semgrep_rules_path: Optional custom Semgrep rules path.
            pip_audit_network_disabled: Optional override for pip-audit network isolation.

        Returns:
            ToolAnalysisSummary: Container holding independent analyzer results.
        """
        logger.info(
            "Starting static analysis pipeline: repo=%s, commit=%s",
            workspace_context.repository_full_name,
            workspace_context.actual_head_sha,
        )

        overall_start = time.monotonic()

        semgrep_task = self.semgrep.run(
            workspace_context=workspace_context,
            custom_rules_path=semgrep_rules_path,
        )
        bandit_task = self.bandit.run(
            workspace_context=workspace_context,
        )
        pip_audit_task = self.pip_audit.run(
            workspace_context=workspace_context,
            network_disabled=pip_audit_network_disabled,
        )

        results = await asyncio.gather(
            semgrep_task, bandit_task, pip_audit_task, return_exceptions=True
        )
        semgrep_raw, bandit_raw, pip_audit_raw = results[0], results[1], results[2]

        # 1. Process Semgrep outcome with exception isolation
        if isinstance(semgrep_raw, BaseException):
            logger.error(
                "Unhandled exception during Semgrep execution: %s", semgrep_raw
            )
            semgrep_result = SemgrepResult(
                analyzer=self.semgrep.analyzer_name,
                analyzer_version=self.semgrep.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=None,
                duration_seconds=0.0,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Unhandled runner exception: {semgrep_raw}",
                raw_stderr=str(semgrep_raw),
            )
        else:
            semgrep_result = semgrep_raw

        # 2. Process Bandit outcome with exception isolation
        if isinstance(bandit_raw, BaseException):
            logger.error("Unhandled exception during Bandit execution: %s", bandit_raw)
            bandit_result = BanditResult(
                analyzer=self.bandit.analyzer_name,
                analyzer_version=self.bandit.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=None,
                duration_seconds=0.0,
                workspace_commit_sha=workspace_context.actual_head_sha,
                findings=[],
                error_message=f"Unhandled runner exception: {bandit_raw}",
                raw_stderr=str(bandit_raw),
            )
        else:
            bandit_result = bandit_raw

        # 3. Process pip-audit outcome with exception isolation
        if isinstance(pip_audit_raw, BaseException):
            logger.error(
                "Unhandled exception during pip-audit execution: %s", pip_audit_raw
            )
            pip_audit_result = PipAuditResult(
                analyzer=self.pip_audit.analyzer_name,
                analyzer_version=self.pip_audit.analyzer_version,
                execution_status=StaticAnalysisExecutionStatus.EXECUTION_ERROR,
                exit_code=None,
                duration_seconds=0.0,
                workspace_commit_sha=workspace_context.actual_head_sha,
                dependency_files_scanned=[],
                findings=[],
                error_message=f"Unhandled runner exception: {pip_audit_raw}",
                raw_stderr=str(pip_audit_raw),
            )
        else:
            pip_audit_result = pip_audit_raw

        total_duration = time.monotonic() - overall_start

        logger.info(
            "Static analysis pipeline completed: repo=%s, duration=%.2fs, "
            "semgrep=%s (findings=%d), bandit=%s (findings=%d), pip-audit=%s (findings=%d)",
            workspace_context.repository_full_name,
            total_duration,
            semgrep_result.execution_status.value,
            len(semgrep_result.findings),
            bandit_result.execution_status.value,
            len(bandit_result.findings),
            pip_audit_result.execution_status.value,
            len(pip_audit_result.findings),
        )

        return ToolAnalysisSummary(
            semgrep=semgrep_result,
            bandit=bandit_result,
            pip_audit=pip_audit_result,
            workspace_commit_sha=workspace_context.actual_head_sha,
            duration_seconds=total_duration,
        )

    async def run_and_normalize(
        self,
        workspace_context: WorkspaceContext,
        semgrep_rules_path: Any | None = None,
        pip_audit_network_disabled: bool | None = None,
        max_evidence_items: int | None = None,
    ) -> tuple[ToolAnalysisSummary, list[EvidenceModel]]:
        """Run all static analyzers and normalize the outputs into canonical EvidenceModels.

        Args:
            workspace_context: Verified workspace snapshot.
            semgrep_rules_path: Optional Semgrep custom rules path.
            pip_audit_network_disabled: Optional network override.
            max_evidence_items: Max evidence items to retain.

        Returns:
            Tuple of (ToolAnalysisSummary, list[EvidenceModel]).
        """
        summary = await self.run_all(
            workspace_context=workspace_context,
            semgrep_rules_path=semgrep_rules_path,
            pip_audit_network_disabled=pip_audit_network_disabled,
        )
        limit = (
            max_evidence_items
            if max_evidence_items is not None
            else getattr(
                self.settings, "STATIC_ANALYSIS_MAX_EVIDENCE_ITEMS_PER_RUN", 1000
            )
        )
        evidence = normalize_tool_analysis_summary(summary, max_items=limit)
        return summary, evidence
