"""Base specialist agent abstraction for domain-specific code review.

Corresponds to Section D and G of the project architecture:
defines the common interface, context contracts, structured output schemas,
and evidence-first grounding mechanisms shared across all domain specialist agents.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.orchestration.errors import (
    InvalidPlannerOutputError,
    InvalidSpecialistOutputError,
    LLMProviderError,
    LLMTimeoutError,
    WorkflowError,
    WorkflowErrorCategory,
)
from app.orchestration.state import ReviewState, extract_review_plan
from app.schemas.enums import EvidenceType, IssueType, VerificationStatus
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan
from app.services.llm.service import LLMService

logger = logging.getLogger(__name__)


class SpecialistContext(BaseModel):
    """Strongly typed, bounded context prepared for specialist agent execution."""

    model_config = ConfigDict(frozen=True)

    review_run_id: str
    repository_full_name: str
    commit_sha: str
    base_sha: str | None = None
    pr_number: int = 0
    pr_title: str | None = None
    pr_author: str | None = None
    pr_metadata: dict[str, Any] = Field(default_factory=dict)

    # Scoping & planning context
    review_plan: ReviewPlan | None = None
    focus_areas: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)

    # Diff context
    changed_files: list[str] = Field(default_factory=list)
    formatted_diff: str = ""
    diff_truncated: bool = False

    # Normalized deterministic evidence items
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)

    # Optional chunking context for large PRs
    is_large_pr: bool = False
    chunking_strategy: str | None = None
    file_chunks: list[list[str]] = Field(default_factory=list)

    # Additional specialist-specific metadata
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpecialistReviewOutput(BaseModel):
    """Normalized structured response emitted by a domain specialist agent."""

    model_config = ConfigDict(populate_by_name=True)

    findings: list[ReviewFinding] = Field(
        default_factory=list,
        description="Candidate review findings discovered by the specialist agent",
    )
    summary: str | None = Field(
        default=None,
        description="Optional brief domain-specific summary of findings or verification notes",
    )


def build_specialist_context(
    state: ReviewState,
    specialist_name: str,
) -> SpecialistContext:
    """Extract and construct a bounded SpecialistContext from current ReviewState."""
    review_run_id = state.get("review_run_id", "unknown")
    commit_sha = state.get("commit_sha", "")
    repo_name = state.get("repository_full_name", "")
    plan = extract_review_plan(state)

    # Extract prepared context if present in execution metadata to avoid re-formatting diffs
    exec_meta = state.get("execution_metadata", {})
    prep_data = exec_meta.get("prepared_context", {})

    if prep_data:
        formatted_diff = prep_data.get("formatted_diff", "")
        diff_truncated = prep_data.get("diff_truncated", False)
        changed_files = prep_data.get("changed_files", state.get("changed_files", []))
        evidence_items = prep_data.get(
            "evidence_items", state.get("evidence_items", [])
        )
        is_large_pr = prep_data.get("is_large_pr", False)
        chunking_strategy = prep_data.get("chunking_strategy")
        file_chunks = prep_data.get("file_chunks", [])
    else:
        formatted_diff = ""
        diff_truncated = state.get("diff_context_truncated", False)
        changed_files = list(state.get("changed_files", []))
        evidence_items = list(state.get("evidence_items", []))
        is_large_pr = False
        chunking_strategy = None
        file_chunks = []

    focus_areas: list[str] = []
    target_files: list[str] = []
    if plan:
        focus_areas = list(plan.focus_areas)
        target_files = (
            list(plan.target_files) if plan.target_files else list(changed_files)
        )
        if plan.is_large_pr:
            is_large_pr = True
            chunking_strategy = plan.chunking_strategy or chunking_strategy
            file_chunks = plan.file_chunks or file_chunks

    return SpecialistContext(
        review_run_id=review_run_id,
        repository_full_name=repo_name,
        commit_sha=commit_sha,
        base_sha=state.get("base_sha"),
        pr_number=state.get("pr_number", 0),
        pr_title=state.get("pr_title"),
        pr_author=state.get("pr_author"),
        pr_metadata=dict(state.get("pr_metadata", {})),
        review_plan=plan,
        focus_areas=focus_areas,
        target_files=target_files,
        changed_files=changed_files,
        formatted_diff=formatted_diff,
        diff_truncated=diff_truncated,
        evidence_items=evidence_items,
        is_large_pr=is_large_pr,
        chunking_strategy=chunking_strategy,
        file_chunks=file_chunks,
        metadata={"specialist_name": specialist_name},
    )


class BaseSpecialistAgent(ABC):
    """Abstract base class for all domain specialist agents.

    Enforces uniform execution, evidence grounding, structured LLM communication,
    and failure isolation across Security, BugLogic, ErrorHandling, and TestAdequacy agents.
    """

    def __init__(
        self,
        name: str,
        issue_type: IssueType,
        system_prompt: str,
        prompt_version: str,
        llm_service: LLMService | None = None,
    ) -> None:
        self.name = name
        self.issue_type = issue_type
        self.system_prompt = system_prompt
        self.prompt_version = prompt_version
        self.llm_service = llm_service or LLMService()

    @abstractmethod
    def build_user_prompt(self, context: SpecialistContext) -> str:
        """Construct the specialist-specific user prompt incorporating relevant evidence."""
        ...

    async def review(self, context: SpecialistContext) -> list[ReviewFinding]:
        """Execute domain-specialized code review and produce grounded candidate findings."""
        start_time = time.monotonic()
        user_prompt = self.build_user_prompt(context)

        logger.info(
            "Specialist [%s] initiated review: run_id=%s, commit=%s, files=%d, evidence_items=%d",
            self.name,
            context.review_run_id,
            context.commit_sha[:8] if context.commit_sha else "unknown",
            len(context.changed_files),
            len(context.evidence_items),
        )

        try:
            raw_output, llm_resp = await self.llm_service.generate_structured(
                prompt=user_prompt,
                schema=SpecialistReviewOutput,
                system_prompt=self.system_prompt,
            )
        except (LLMTimeoutError, LLMProviderError):
            raise
        except (InvalidPlannerOutputError, ValidationError) as exc:
            logger.error(
                "Specialist [%s] received malformed output: %s",
                self.name,
                exc,
                exc_info=True,
            )
            raise InvalidSpecialistOutputError(
                message=f"Specialist agent [{self.name}] output failed validation: {exc}",
                agent_name=self.name,
            ) from exc
        except Exception as exc:
            logger.error(
                "Specialist [%s] encountered unexpected failure: %s",
                self.name,
                exc,
                exc_info=True,
            )
            raise InvalidSpecialistOutputError(
                message=f"Specialist agent [{self.name}] execution failed: {exc}",
                agent_name=self.name,
            ) from exc

        duration = time.monotonic() - start_time
        candidate_findings = self._enrich_and_ground_findings(
            raw_output.findings, context, duration, llm_resp.total_tokens
        )

        logger.info(
            "Specialist [%s] completed review: run_id=%s, candidate_findings=%d, duration=%.2fs, tokens=%d",
            self.name,
            context.review_run_id,
            len(candidate_findings),
            duration,
            llm_resp.total_tokens,
        )

        return candidate_findings

    def _enrich_and_ground_findings(
        self,
        raw_findings: list[ReviewFinding],
        context: SpecialistContext,
        _duration: float,
        _tokens: int,
    ) -> list[ReviewFinding]:
        """Normalize, ground in evidence, and attach provenance to candidate findings."""
        grounded: list[ReviewFinding] = []

        for finding in raw_findings:
            # 1. Enforce provenance invariants
            finding.agent_name = self.name
            finding.verification_status = VerificationStatus.UNVERIFIED
            finding.confidence_score = 0.0  # Must be calibrated by downstream Critic

            # Ensure default issue_type aligns with agent domain if unset
            if not finding.issue_type:
                finding.issue_type = self.issue_type

            # Ensure raw confidence is within valid range
            if finding.raw_confidence is None:
                finding.raw_confidence = 0.8
            else:
                finding.raw_confidence = max(
                    0.0, min(1.0, round(finding.raw_confidence, 3))
                )

            # 2. Evidence Grounding Enforcement
            # Corroborate with static analysis evidence from context if matching file and line span
            matching_static_evidence = self._find_matching_static_evidence(
                finding.affected_file, finding.line_number, context.evidence_items
            )
            for ev_dict in matching_static_evidence:
                try:
                    ev_model = EvidenceModel.model_validate(ev_dict)
                    if not any(
                        e.file_path == ev_model.file_path
                        and e.start_line == ev_model.start_line
                        and e.rule_or_cve_id == ev_model.rule_or_cve_id
                        for e in finding.evidence
                    ):
                        finding.evidence.append(ev_model)
                except ValidationError:
                    pass

            # 3. If evidence is still empty, synthesize grounded diff evidence from coordinates
            if not finding.evidence:
                diff_snippet = self._extract_diff_snippet_for_line(
                    finding.affected_file, finding.line_number, context.formatted_diff
                )
                finding.evidence.append(
                    EvidenceModel(
                        evidence_type=EvidenceType.DIFF_HUNK,
                        file_path=finding.affected_file,
                        start_line=finding.line_number,
                        end_line=finding.line_number,
                        snippet=diff_snippet
                        or f"Line {finding.line_number} in {finding.affected_file}",
                    )
                )

            grounded.append(finding)

        return grounded

    def _find_matching_static_evidence(
        self,
        file_path: str,
        line_number: int,
        evidence_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Identify static tool evidence items matching file and proximate line range."""
        matches: list[dict[str, Any]] = []
        clean_file = file_path.strip().lower()

        for item in evidence_items:
            ev_file = str(item.get("file_path", "")).strip().lower()
            if not ev_file:
                continue

            # Check if file paths match exactly or by suffix
            if (
                clean_file == ev_file
                or clean_file.endswith(ev_file)
                or ev_file.endswith(clean_file)
            ):
                s_line = int(item.get("start_line", 1))
                e_line = int(item.get("end_line", s_line))
                # Match if line is within range or within 3 lines proximity
                if (s_line - 3) <= line_number <= (e_line + 3):
                    matches.append(item)

        return matches

    def _extract_diff_snippet_for_line(
        self, file_path: str, line_number: int, formatted_diff: str
    ) -> str:
        """Extract a representative snippet around line_number from formatted diff."""
        if not formatted_diff:
            return f"Line {line_number} in {file_path}"

        lines = formatted_diff.splitlines()
        matching_lines: list[str] = []
        for line in lines:
            if file_path in line or (line.startswith("+") and len(matching_lines) < 3):
                matching_lines.append(line[:120])
                if len(matching_lines) >= 3:
                    break

        if matching_lines:
            return "\n".join(matching_lines)
        return f"Line {line_number} in {file_path}"

    async def execute_node(
        self, state: ReviewState, raise_exceptions: bool = False
    ) -> dict[str, Any]:
        """LangGraph node execution wrapper with failure isolation and telemetry recording."""
        start_time = time.monotonic()
        review_run_id = state.get("review_run_id", "unknown")

        logger.info("LangGraph node [%s] started: run_id=%s", self.name, review_run_id)

        try:
            context = build_specialist_context(state, self.name)
            findings = await self.review(context)
            duration = time.monotonic() - start_time

            serialized_findings = [f.model_dump(by_alias=True) for f in findings]
            logger.info(
                "LangGraph node [%s] completed successfully: run_id=%s, findings=%d, duration=%.2fs",
                self.name,
                review_run_id,
                len(serialized_findings),
                duration,
            )

            return {
                "candidate_findings": serialized_findings,
                "specialist_errors": [],
            }

        except WorkflowError as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "LangGraph node [%s] failed with WorkflowError: run_id=%s, category=%s, error=%s",
                self.name,
                review_run_id,
                exc.category.value,
                exc.message,
            )
            if raise_exceptions:
                raise

            err_info = {
                "agent_name": self.name,
                "error": exc.message,
                "error_category": exc.category.value,
                "retryable": exc.retryable,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            return {
                "candidate_findings": [],
                "specialist_errors": [err_info],
                "error_messages": [f"[{self.name}] {exc.message}"],
            }

        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "LangGraph node [%s] encountered unexpected error: run_id=%s, error=%s",
                self.name,
                review_run_id,
                exc,
                exc_info=True,
            )
            if raise_exceptions:
                raise

            err_info = {
                "agent_name": self.name,
                "error": str(exc),
                "error_category": WorkflowErrorCategory.WORKFLOW_EXECUTION_FAILURE.value,
                "retryable": False,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            return {
                "candidate_findings": [],
                "specialist_errors": [err_info],
                "error_messages": [f"[{self.name}] Unexpected error: {exc}"],
            }
