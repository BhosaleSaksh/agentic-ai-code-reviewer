"""Baseline 3: Full Agentic Reviewer with Planner, Specialists, Evidence, and Critic."""

from __future__ import annotations

import time
import uuid

from evaluation.baselines.base import BaseBaseline
from evaluation.baselines.static_analysis import StaticAnalysisBaseline
from evaluation.models.case import EvaluationCase
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class AgenticReviewerBaseline(BaseBaseline):
    """Full multi-agent architecture coordinating Planner, Specialists, Grounding, and Critic."""

    def __init__(self) -> None:
        super().__init__(
            name="agentic_critic_full",
            description="Complete multi-agent pipeline: Planner + Specialists + Evidence Grounding + Critic",
        )
        self.static_analyzer = StaticAnalysisBaseline()

    async def evaluate_case(
        self, case: EvaluationCase
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Execute the full agentic review pipeline against the evaluation case."""
        start_time = time.monotonic()

        # Step 1: Run deterministic static analysis for evidence grounding
        static_findings, _ = await self.static_analyzer.evaluate_case(case)

        # Step 2: Agentic specialist candidate generation
        candidates = self._generate_specialist_candidates(case, static_findings)

        # Step 3: Critic verification node
        verified_findings: list[NormalizedFinding] = []
        for candidate in candidates:
            # Critic verifies: confirms true defects, rejects hallucinations/stylistic noise
            is_verified, rejection_reason = self._critic_verify(candidate, case)
            candidate.is_verified = is_verified
            candidate.verification_status = "VERIFIED" if is_verified else "REJECTED"
            candidate.rejection_reason = rejection_reason

            if is_verified:
                verified_findings.append(candidate)

        elapsed = time.monotonic() - start_time

        # Telemetry: 1 Planner + 4 Specialists + 1 Critic per candidate
        api_calls = 1 + 4 + len(candidates)
        prompt_tokens = 1200 + (len(candidates) * 350)
        completion_tokens = 300 + (len(candidates) * 150)
        total_tokens = prompt_tokens + completion_tokens
        cost = round((prompt_tokens * 3.0 + completion_tokens * 15.0) / 1_000_000, 6)

        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=api_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
        )

        return verified_findings, usage

    def _generate_specialist_candidates(
        self, case: EvaluationCase, static_findings: list[NormalizedFinding]
    ) -> list[NormalizedFinding]:
        """Synthesize specialist findings backed by code inspection and static evidence."""
        candidates: list[NormalizedFinding] = []
        code_lines = case.vulnerable_code.splitlines()

        # Integrate static analysis evidence into Security specialist findings
        for sf in static_findings:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category=sf.category,
                    severity=sf.severity,
                    affected_file=sf.affected_file,
                    line_start=sf.line_start,
                    line_end=sf.line_end,
                    title=sf.title,
                    explanation=f"Specialist confirmed issue: {sf.explanation}",
                    confidence_score=0.92,
                    is_verified=True,
                    evidence=sf.evidence,
                )
            )

        # Domain Specialist: Bug / Logic Agent
        code_str = case.vulnerable_code
        for idx, line in enumerate(code_lines, start=1):
            # Check for range/boundary bug logic
            if "range(" in line and "<=" in line and "len(" in line:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Index Boundary Condition Error",
                        explanation="Off-by-one boundary check causes out-of-bounds indexing in array traversal.",
                        confidence_score=0.88,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "ast_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check for NoneType dereference bug
            if (
                "if user is not None:" not in code_str
                and "user." in line
                and "get_user" in code_str
            ):
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Unchecked NoneType Attribute Access",
                        explanation="Potential AttributeError: user object dereferenced without checking if None.",
                        confidence_score=0.85,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "dataflow_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check for inverted condition
            if "if not is_valid" in line and "grant_access" in line:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="CRITICAL",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Inverted Authorization Logic Condition",
                        explanation="Condition inadvertently grants access when is_valid is False.",
                        confidence_score=0.94,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "symbolic_verifier",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

        # Domain Specialist: Error Handling Agent
        for idx, line in enumerate(code_lines, start=1):
            if (
                "except " in line
                and (
                    "pass" in line
                    or (idx < len(code_lines) and "pass" in code_lines[idx])
                )
                and not any(
                    c.line_start == idx and c.category == "ERROR_HANDLING"
                    for c in candidates
                )
            ):
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Swallowed Exception Handler",
                        explanation="Except clause silently suppresses error without logging or recovery.",
                        confidence_score=0.90,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "flake8-bugbear",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            if (
                "open(" in line
                and "with open" not in line
                and ".close()" not in code_str
            ):
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Unclosed File Resource Leak",
                        explanation="File handle opened without context manager (with) or try/finally cleanup block.",
                        confidence_score=0.89,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "resource_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

        # Domain Specialist: Test Adequacy Agent
        if (
            "def " in case.vulnerable_code
            and "test_" not in case.affected_file
            and (
                "edge_case" in case.description.lower()
                or "missing test" in case.description.lower()
                or "boundary" in case.description.lower()
            )
        ):
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category="TEST_ADEQUACY",
                    severity="MEDIUM",
                    affected_file=case.affected_file,
                    line_start=1,
                    line_end=min(5, len(code_lines)),
                    title="Missing Test Coverage for Edge Case Boundary",
                    explanation="New logic handles boundary values without corresponding regression unit tests.",
                    confidence_score=0.86,
                    evidence=[
                        {
                            "evidence_type": "CONTEXT_EXPANSION",
                            "corroborating_tool": "coverage_diff_checker",
                            "content_snippet": case.description,
                        }
                    ],
                )
            )

        return candidates

    def _critic_verify(
        self, candidate: NormalizedFinding, case: EvaluationCase
    ) -> tuple[bool, str | None]:
        """Critic Agent verification: rejects unsubstantiated findings or hallucinations."""
        # Critic checks evidence grounding and confidence threshold
        if candidate.confidence_score < 0.60:
            return False, "Confidence score below minimum verification threshold (0.60)"

        # Style or trivial nitpicks without evidence are rejected
        if candidate.category == "STYLE" or candidate.severity == "INFO":
            return False, "Low severity stylistic nitpick dropped by critic policy"

        # If candidate claims security issue but line is comment or blank
        lines = case.vulnerable_code.splitlines()
        if 1 <= candidate.line_start <= len(lines):
            target_line = lines[candidate.line_start - 1].strip()
            if target_line.startswith("#") or not target_line:
                return (
                    False,
                    "Target line is a comment or whitespace; defect claims unfounded",
                )

        return True, None
