"""Planner Agent implementation for automated PR triage, scoping, and specialist routing.

Corresponds to Section D.1 and G of the project architecture:
analyzes PR diff context and deterministic static analysis evidence to produce
the canonical ReviewPlan contract grounding future specialist execution.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.agents.planner_prompt import (
    PLANNER_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_planner_user_prompt,
)
from app.orchestration.context_builder import PreparedPlannerContext
from app.orchestration.errors import (
    InvalidPlannerOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.review_plan import ReviewPlan
from app.services.llm.service import LLMService

logger = logging.getLogger(__name__)

# Canonical specialist agent names recognized by the orchestration DAG
KNOWN_SPECIALIST_AGENTS = {
    "security_agent",
    "bug_logic_agent",
    "error_handling_agent",
    "test_adequacy_agent",
}


class PlannerAgent:
    """Lead Planning and Triage Agent responsible for generating the ReviewPlan."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    async def plan(self, context: PreparedPlannerContext) -> ReviewPlan:
        """Generate, validate, and ground a canonical ReviewPlan from prepared PR context."""
        start_time = time.monotonic()
        user_prompt = build_planner_user_prompt(context)

        logger.info(
            "Planner agent initiating planning: commit=%s, files=%d, evidence_items=%d, is_large_pr=%s",
            context.commit_sha[:8],
            context.total_files,
            len(context.evidence_items),
            context.is_large_pr,
        )

        try:
            raw_plan, llm_resp = await self.llm_service.generate_structured(
                prompt=user_prompt,
                schema=ReviewPlan,
                system_prompt=PLANNER_SYSTEM_PROMPT,
            )
        except (LLMTimeoutError, LLMProviderError, InvalidPlannerOutputError):
            raise
        except Exception as exc:
            logger.error(
                "Planner agent encountered unhandled failure: %s", exc, exc_info=True
            )
            raise InvalidPlannerOutputError(
                message=f"Planner agent failure during execution: {exc}"
            ) from exc

        # Post-validation and evidence-first grounding enforcement
        validated_plan = self._enforce_evidence_grounding_and_bounds(raw_plan, context)

        duration = time.monotonic() - start_time
        # Record execution metadata on the plan
        plan_meta: dict[str, Any] = dict(validated_plan.metadata)
        plan_meta.update(
            {
                "planner_duration_seconds": round(duration, 3),
                "planner_prompt_version": PROMPT_VERSION,
                "planner_total_tokens": llm_resp.total_tokens,
                "diff_truncated": context.diff_truncated,
                "evidence_truncated": context.evidence_truncated,
            }
        )
        validated_plan.metadata = plan_meta

        logger.info(
            "Planner completed plan successfully: scope=%s, active_agents=%s, "
            "focus_areas=%d, duration=%.2fs, tokens=%d",
            validated_plan.review_scope,
            validated_plan.active_agents,
            len(validated_plan.focus_areas),
            duration,
            llm_resp.total_tokens,
        )

        return validated_plan

    def _enforce_evidence_grounding_and_bounds(
        self, plan: ReviewPlan, context: PreparedPlannerContext
    ) -> ReviewPlan:
        """Enforce architectural invariants on the generated ReviewPlan."""
        # 1. Normalize active agents to known specialist list
        valid_agents = [
            agent for agent in plan.active_agents if agent in KNOWN_SPECIALIST_AGENTS
        ]

        # 2. Evidence-First Principle (Section 10):
        # If deterministic static evidence is present (Semgrep, Bandit, pip-audit),
        # security_agent MUST be activated.
        has_security_evidence = any(
            item.get("corroborating_tool")
            in ("semgrep", "bandit", "pip_audit", "pip-audit")
            or "security" in str(item.get("evidence_type", "")).lower()
            for item in context.evidence_items
        )

        if has_security_evidence and "security_agent" not in valid_agents:
            logger.info(
                "Enforcing evidence-first activation: adding 'security_agent' due to static findings"
            )
            valid_agents.insert(0, "security_agent")

        # Fall back to at least bug_logic_agent if no agents selected and PR has changes
        if not valid_agents and context.total_files > 0:
            valid_agents.append("bug_logic_agent")

        # 3. Target files consistency: default to changed_files if empty
        target_files = plan.target_files
        if not target_files and context.changed_files:
            target_files = list(context.changed_files)

        # 4. Large PR invariants
        is_large = plan.is_large_pr or context.is_large_pr
        chunking_strategy = plan.chunking_strategy
        file_chunks = plan.file_chunks

        if is_large:
            if not chunking_strategy or chunking_strategy == "NONE":
                chunking_strategy = context.chunking_strategy or "FILE_MODULE"
            if not file_chunks and context.file_chunks:
                file_chunks = context.file_chunks

        # Construct updated clean ReviewPlan
        return ReviewPlan(
            review_scope=plan.review_scope,
            active_agents=valid_agents,
            focus_areas=plan.focus_areas,
            target_files=target_files,
            is_large_pr=is_large,
            chunking_strategy=chunking_strategy,
            file_chunks=file_chunks,
            reasoning=plan.reasoning
            or "Automated review plan derived from PR context and static evidence.",
            metadata=plan.metadata,
        )
