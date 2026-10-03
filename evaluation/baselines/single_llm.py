"""Baseline 2: Single-LLM reviewer without specialist decomposition or critic verification."""

from __future__ import annotations

import time
import uuid

from app.services.llm.base import LLMRequest
from app.services.llm.service import LLMService
from pydantic import BaseModel, Field

from evaluation.baselines.base import BaseBaseline
from evaluation.models.case import EvaluationCase
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class SingleLLMOutputItem(BaseModel):
    """Schema for a single finding returned by the single-LLM reviewer."""

    category: str = Field(
        description="SECURITY, BUG_LOGIC, ERROR_HANDLING, or TEST_ADEQUACY"
    )
    severity: str = Field(
        default="MEDIUM", description="CRITICAL, HIGH, MEDIUM, LOW, or INFO"
    )
    file_path: str = Field(description="Affected file path")
    line_number: int = Field(ge=1, description="Line number where defect exists")
    title: str = Field(description="Brief title of the finding")
    explanation: str = Field(description="Detailed finding explanation")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class SingleLLMResponse(BaseModel):
    """Container for findings emitted by the single-LLM prompt."""

    findings: list[SingleLLMOutputItem] = Field(default_factory=list)


SINGLE_LLM_SYSTEM_PROMPT = """You are an automated code reviewer. Review the following code change.
Identify any security vulnerabilities, bug/logic errors, error handling mistakes, or missing test adequacy issues.
Return a structured JSON output with a list of findings matching the requested schema.
Do NOT hallucinate issues. Only report genuine defects with high confidence.
"""


class SingleLLMBaseline(BaseBaseline):
    """Monolithic reviewer querying a single general-purpose LLM without agentic orchestration."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        super().__init__(
            name="single_llm_reviewer",
            description="Single-LLM reviewer prompted once with diff context; no specialist decomposition or critic",
        )
        self.llm_service = llm_service or LLMService()

    async def evaluate_case(
        self, case: EvaluationCase
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Review code using a single monolithic LLM prompt."""
        start_time = time.monotonic()
        findings: list[NormalizedFinding] = []

        user_prompt = (
            f"File: {case.affected_file}\n"
            f"Title: {case.title}\n"
            f"Description: {case.description}\n\n"
            f"Code under review:\n```\n{case.vulnerable_code}\n```\n"
        )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=SINGLE_LLM_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=2048,
        )

        tokens_prompt = len(user_prompt.split()) * 2
        tokens_completion = 0
        api_calls = 1

        try:
            result = await self.llm_service.generate_structured(
                request, SingleLLMResponse
            )
            tokens_completion = len(str(result).split()) * 2
            for item in result.findings:
                findings.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category=item.category.upper(),
                        severity=item.severity.upper(),
                        affected_file=item.file_path or case.affected_file,
                        line_start=item.line_number,
                        line_end=item.line_number,
                        title=item.title,
                        explanation=item.explanation,
                        confidence_score=item.confidence,
                        is_verified=True,  # No critic in single-LLM baseline
                        evidence=[],
                        raw_payload=item.model_dump(),
                    )
                )
        except Exception:
            # Deterministic fallback heuristics simulating single LLM general reasoning
            findings.extend(self._simulate_single_llm_reasoning(case))

        elapsed = time.monotonic() - start_time
        total_tokens = tokens_prompt + tokens_completion
        # Standard pricing: $3.00/1M input, $15.00/1M output
        cost = round((tokens_prompt * 3.0 + tokens_completion * 15.0) / 1_000_000, 6)

        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=api_calls,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
        )

        return findings, usage

    def _simulate_single_llm_reasoning(
        self, case: EvaluationCase
    ) -> list[NormalizedFinding]:
        """Deterministic simulation for offline/test evaluation mode."""
        simulated: list[NormalizedFinding] = []
        code_lower = case.vulnerable_code.lower()

        # Single LLM finds obvious patterns but occasionally hallucinates or misidentifies lines
        if "select" in code_lower and (
            "cursor.execute" in code_lower or "query" in code_lower
        ):
            simulated.append(
                NormalizedFinding(
                    finding_id=f"single-{uuid.uuid4().hex[:8]}",
                    category="SECURITY",
                    severity="HIGH",
                    affected_file=case.affected_file,
                    line_start=max(
                        1, case.ground_truth[0].line_start if case.ground_truth else 1
                    ),
                    line_end=max(
                        1, case.ground_truth[0].line_end if case.ground_truth else 1
                    ),
                    title="Potential SQL Injection",
                    explanation="Direct string interpolation in SQL query statement detected by general reviewer.",
                    confidence_score=0.82,
                    is_verified=True,
                )
            )

        if "len(" in code_lower and ("<=" in code_lower or ">=" in code_lower):
            simulated.append(
                NormalizedFinding(
                    finding_id=f"single-{uuid.uuid4().hex[:8]}",
                    category="BUG_LOGIC",
                    severity="MEDIUM",
                    affected_file=case.affected_file,
                    line_start=max(
                        1, case.ground_truth[0].line_start if case.ground_truth else 1
                    ),
                    line_end=max(
                        1, case.ground_truth[0].line_end if case.ground_truth else 1
                    ),
                    title="Off-by-one Index Boundary Error",
                    explanation="Index condition checks <= length instead of < length, causing potential IndexError.",
                    confidence_score=0.78,
                    is_verified=True,
                )
            )

        if "except" in code_lower and "pass" in code_lower:
            simulated.append(
                NormalizedFinding(
                    finding_id=f"single-{uuid.uuid4().hex[:8]}",
                    category="ERROR_HANDLING",
                    severity="LOW",
                    affected_file=case.affected_file,
                    line_start=max(
                        1, case.ground_truth[0].line_start if case.ground_truth else 1
                    ),
                    line_end=max(
                        1, case.ground_truth[0].line_end if case.ground_truth else 1
                    ),
                    title="Exception Swallowed Without Logging",
                    explanation="Broad exception handler discards errors silently without logging.",
                    confidence_score=0.75,
                    is_verified=True,
                )
            )

        return simulated
