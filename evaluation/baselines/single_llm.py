"""Baseline 2: Single-LLM reviewer without specialist decomposition or critic verification."""

from __future__ import annotations

import time
import uuid

from app.services.llm.base import LLMRequest
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService
from pydantic import BaseModel, Field

from evaluation.baselines.base import BaseBaseline
from evaluation.models.case import EvaluationInput
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

    def __init__(
        self, llm_service: LLMService | None = None, mode: str = "offline"
    ) -> None:
        super().__init__(
            name="single_llm_reviewer",
            description="Single-LLM reviewer prompted once with diff context; no specialist decomposition or critic",
            mode=mode,
        )
        self.llm_service = llm_service or LLMService()
        if self.mode == "real":
            provider_cfg = (self.llm_service.settings.LLM_PROVIDER or "openai").lower()
            self.provider_name = provider_cfg
            self.model_name = getattr(
                self.llm_service.settings,
                f"{provider_cfg.upper()}_MODEL",
                "default-model",
            )
        else:
            self.provider_name = "offline_simulator"
            self.model_name = "deterministic_single_llm_mock"

    async def evaluate_case(
        self, case: EvaluationInput
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Review code using a single monolithic LLM prompt."""
        start_time = time.perf_counter()
        findings: list[NormalizedFinding] = []

        if self.mode == "real":
            # Verify provider configuration
            provider = (
                (self.llm_service.settings.LLM_PROVIDER or "mock").strip().lower()
            )
            has_creds = bool(
                (provider == "openai" and self.llm_service.settings.OPENAI_API_KEY)
                or (
                    provider == "anthropic"
                    and self.llm_service.settings.ANTHROPIC_API_KEY
                )
                or (
                    provider in {"google", "gemini"}
                    and self.llm_service.settings.GOOGLE_API_KEY
                )
            )

            if not has_creds or isinstance(self.llm_service._provider, MockLLMProvider):
                raise RuntimeError(
                    f"Real LLM mode requested for {self.name}, but {provider.upper()} API credentials "
                    "are not configured. Provide API keys in environment or run with '--mode offline'."
                )

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
            api_calls = 1

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

            elapsed = time.perf_counter() - start_time
            total_tokens = tokens_prompt + tokens_completion
            cost = round(
                (tokens_prompt * 3.0 + tokens_completion * 15.0) / 1_000_000, 6
            )

            usage = ResourceUsage(
                latency_seconds=round(elapsed, 4),
                api_calls=api_calls,
                prompt_tokens=tokens_prompt,
                completion_tokens=tokens_completion,
                total_tokens=total_tokens,
                estimated_cost_usd=cost,
            )
            return findings, usage

        # OFFLINE DETERMINISTIC SIMULATION MODE
        # Inspects input code directly with zero ground-truth leakage
        findings = self._simulate_offline_reviewer(case)
        elapsed = time.perf_counter() - start_time

        prompt_tokens = len(case.vulnerable_code.split()) * 2
        completion_tokens = len(findings) * 50
        total_tokens = prompt_tokens + completion_tokens
        cost = round((prompt_tokens * 3.0 + completion_tokens * 15.0) / 1_000_000, 6)

        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
        )
        return findings, usage

    def _simulate_offline_reviewer(
        self, case: EvaluationInput
    ) -> list[NormalizedFinding]:
        """Deterministic simulation for offline/test evaluation mode without ground truth leakage."""
        simulated: list[NormalizedFinding] = []
        code_lines = case.vulnerable_code.splitlines()

        for idx, line in enumerate(code_lines, start=1):
            line_lower = line.lower()

            # Security: SQL injection pattern
            if ("cursor.execute" in line_lower or "query" in line_lower) and any(
                kw in line_lower for kw in ['f"', "f'", " % ", ".format"]
            ):
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Potential SQL Injection",
                        explanation="Direct parameter interpolation in SQL query statement detected by general reviewer.",
                        confidence_score=0.82,
                        is_verified=True,
                        evidence=[],
                    )
                )

            # Security: hardcoded secret pattern
            if any(
                k in line_lower for k in ["secret_key =", "jwt_secret =", "api_key ="]
            ) and any(q in line for q in ['"', "'"]):
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Hardcoded Secret Key Detected",
                        explanation="Cryptographic key or secret assigned directly in source code.",
                        confidence_score=0.85,
                        is_verified=True,
                        evidence=[],
                    )
                )

            # Security: unsafe deserialization
            if "pickle.loads" in line_lower:
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="CRITICAL",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Unsafe Pickle Deserialization",
                        explanation="Deserializing untrusted data via pickle can lead to arbitrary code execution.",
                        confidence_score=0.90,
                        is_verified=True,
                        evidence=[],
                    )
                )

            # Security: weak hash
            if "hashlib.md5" in line_lower or "hashlib.sha1" in line_lower:
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Insecure Hash Function (MD5/SHA1)",
                        explanation="MD5 or SHA1 is cryptographically weak and collision-prone.",
                        confidence_score=0.88,
                        is_verified=True,
                        evidence=[],
                    )
                )

            # Security: command injection
            if "subprocess." in line_lower and "shell=true" in line_lower:
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Shell Command Injection Risk",
                        explanation="Running subprocess with shell=True and dynamic arguments allows command injection.",
                        confidence_score=0.85,
                        is_verified=True,
                        evidence=[],
                    )
                )

            # Bug logic: boundary condition
            if "range(len(" in line_lower and "+ 1" in line_lower:
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Off-by-One Boundary Condition",
                        explanation="range(len(...) + 1) causes out-of-bounds IndexError.",
                        confidence_score=0.80,
                        is_verified=True,
                        evidence=[],
                    )
                )

            # Error handling: broad exception pass
            if "except" in line_lower and "pass" in line_lower:
                simulated.append(
                    NormalizedFinding(
                        finding_id=f"single-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="LOW",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Exception Swallowed Without Logging",
                        explanation="Broad exception handler discards errors silently without logging or recovery.",
                        confidence_score=0.75,
                        is_verified=True,
                        evidence=[],
                    )
                )

        return simulated
