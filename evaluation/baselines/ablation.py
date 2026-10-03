"""Ablation studies isolating the effect of critic verification and static analysis evidence."""

from __future__ import annotations

import time

from evaluation.baselines.agentic import AgenticReviewerBaseline
from evaluation.baselines.base import BaseBaseline
from evaluation.models.case import EvaluationCase
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class AgenticNoCriticBaseline(BaseBaseline):
    """Ablation 1: Multi-agent specialists without Critic verification."""

    def __init__(self) -> None:
        super().__init__(
            name="agentic_no_critic",
            description="Agentic pipeline with Planner + Specialists, but critic verification is omitted",
        )
        self._core_agent = AgenticReviewerBaseline()

    async def evaluate_case(
        self, case: EvaluationCase
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Produce raw candidate findings without filtering through the Critic node."""
        start_time = time.monotonic()

        # Step 1: Static analysis
        static_findings, _ = await self._core_agent.static_analyzer.evaluate_case(case)

        # Step 2: Specialists generate raw candidate findings
        candidates = self._core_agent._generate_specialist_candidates(
            case, static_findings
        )

        # In No-Critic ablation, ALL candidate findings are emitted unconditionally
        for cand in candidates:
            cand.is_verified = True
            cand.verification_status = "UNVERIFIED_CANDIDATE"

        elapsed = time.monotonic() - start_time
        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=5,  # 1 Planner + 4 Specialists, 0 Critic calls
            prompt_tokens=1200,
            completion_tokens=300,
            total_tokens=1500,
            estimated_cost_usd=round((1200 * 3.0 + 300 * 15.0) / 1_000_000, 6),
        )

        return candidates, usage


class AgenticNoStaticEvidenceBaseline(BaseBaseline):
    """Ablation 2: Multi-agent specialists and Critic, but without static analysis evidence grounding."""

    def __init__(self) -> None:
        super().__init__(
            name="agentic_no_static_evidence",
            description="Agentic pipeline with Planner + Specialists + Critic, but static analysis tools are omitted",
        )
        self._core_agent = AgenticReviewerBaseline()

    async def evaluate_case(
        self, case: EvaluationCase
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Execute agentic pipeline without static analysis grounding evidence."""
        start_time = time.monotonic()

        # Step 1: Skip static analysis (empty evidence)
        empty_static: list[NormalizedFinding] = []

        # Step 2: Specialists produce candidates without static evidence
        candidates = self._core_agent._generate_specialist_candidates(
            case, empty_static
        )

        # Strip any static analysis evidence
        for cand in candidates:
            cand.evidence = [
                e for e in cand.evidence if e.get("evidence_type") != "STATIC_ANALYSIS"
            ]

        # Step 3: Critic verification
        verified_findings: list[NormalizedFinding] = []
        for candidate in candidates:
            is_verified, reason = self._core_agent._critic_verify(candidate, case)
            candidate.is_verified = is_verified
            candidate.rejection_reason = reason
            if is_verified:
                verified_findings.append(candidate)

        elapsed = time.monotonic() - start_time
        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=1 + 4 + len(candidates),
            prompt_tokens=1000 + (len(candidates) * 300),
            completion_tokens=250 + (len(candidates) * 120),
            total_tokens=1250 + (len(candidates) * 420),
            estimated_cost_usd=round((1000 * 3.0 + 250 * 15.0) / 1_000_000, 6),
        )

        return verified_findings, usage
