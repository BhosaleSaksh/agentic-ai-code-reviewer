"""LangGraph Review Workflow StateGraph definition and execution orchestration.

Constructs the stateful directed acyclic graph (DAG) connecting context preparation,
the Planner Agent, parallel domain specialist fan-out (Security, BugLogic, ErrorHandling,
TestAdequacy), and candidate finding aggregation with failure isolation, checkpointer
support, and telemetry per Section D, G, and 9-11.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.agents.planner import KNOWN_SPECIALIST_AGENTS, PlannerAgent
from app.orchestration.checkpoint import create_checkpointer, get_thread_config
from app.orchestration.context_builder import (
    PlannerContextBuilder,
    PreparedPlannerContext,
)
from app.orchestration.errors import (
    ContextPreparationError,
    EvidenceValidationError,
    LLMProviderError,
    LLMTimeoutError,
    WorkflowError,
    WorkflowErrorCategory,
)
from app.orchestration.state import (
    ReviewState,
    extract_candidate_findings,
    extract_rejected_findings,
    extract_review_plan,
    extract_verified_findings,
)
from app.schemas.diff import ParsedDiff
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan

if TYPE_CHECKING:
    from app.agents.bug_logic import BugLogicAgent
    from app.agents.critic import CriticAgent
    from app.agents.error_handling import ErrorHandlingAgent
    from app.agents.security import SecurityAgent
    from app.agents.test_adequacy import TestAdequacyAgent
    from app.services.evidence.grounding_service import EvidenceGroundingService

logger = logging.getLogger(__name__)


class ReviewGraphBuilder:
    """Builder for constructing and compiling the LangGraph code review StateGraph."""

    def __init__(
        self,
        planner_agent: PlannerAgent | None = None,
        security_agent: SecurityAgent | None = None,
        bug_logic_agent: BugLogicAgent | None = None,
        error_handling_agent: ErrorHandlingAgent | None = None,
        test_adequacy_agent: TestAdequacyAgent | None = None,
        critic_agent: CriticAgent | None = None,
        grounding_service: EvidenceGroundingService | None = None,
        context_builder: PlannerContextBuilder | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        raise_exceptions: bool = False,
    ) -> None:
        self.planner_agent = planner_agent or PlannerAgent()

        if security_agent is not None:
            self.security_agent = security_agent
        else:
            from app.agents.security import SecurityAgent

            self.security_agent = SecurityAgent()

        if bug_logic_agent is not None:
            self.bug_logic_agent = bug_logic_agent
        else:
            from app.agents.bug_logic import BugLogicAgent

            self.bug_logic_agent = BugLogicAgent()

        if error_handling_agent is not None:
            self.error_handling_agent = error_handling_agent
        else:
            from app.agents.error_handling import ErrorHandlingAgent

            self.error_handling_agent = ErrorHandlingAgent()

        if test_adequacy_agent is not None:
            self.test_adequacy_agent = test_adequacy_agent
        else:
            from app.agents.test_adequacy import TestAdequacyAgent

            self.test_adequacy_agent = TestAdequacyAgent()

        if grounding_service is not None:
            self.grounding_service = grounding_service
        else:
            from app.services.evidence.grounding_service import EvidenceGroundingService

            self.grounding_service = EvidenceGroundingService()

        if critic_agent is not None:
            self.critic_agent = critic_agent
        else:
            from app.agents.critic import CriticAgent

            self.critic_agent = CriticAgent(grounding_service=self.grounding_service)

        self.context_builder = context_builder or PlannerContextBuilder()
        self.checkpointer = checkpointer or create_checkpointer()
        self.raise_exceptions = raise_exceptions

    def _prepare_review_context_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 1: Prepare, bound, sanitize, and validate context for review planning."""
        start_time = time.monotonic()
        review_run_id = state.get("review_run_id", "unknown")
        commit_sha = state.get("commit_sha", "")

        logger.info(
            "Graph node [prepare_review_context] started: run_id=%s, commit=%s",
            review_run_id,
            commit_sha[:8] if commit_sha else "unknown",
        )

        try:
            if not commit_sha:
                raise EvidenceValidationError(
                    message="Missing required commit_sha in graph state",
                    expected_commit_sha="<provided_sha>",
                )

            # Reconstruct PR context dictionary
            pr_ctx_dict = {
                "repository_full_name": state.get("repository_full_name", ""),
                "head_sha": commit_sha,
                "base_sha": state.get("base_sha"),
                "title": state.get("pr_title", ""),
                "author": state.get("pr_author", ""),
                "changed_files": state.get("changed_files", []),
                "parsed_diff": state.get("parsed_diff"),
            }

            prep_ctx = self.context_builder.build(
                pr_context=pr_ctx_dict,
                evidence_items=state.get("evidence_items", []),
                expected_commit_sha=commit_sha,
            )

            duration = time.monotonic() - start_time
            exec_meta = dict(state.get("execution_metadata", {}))
            durations = dict(exec_meta.get("durations", {}))
            durations["prepare_context_seconds"] = round(duration, 3)
            exec_meta["durations"] = durations
            exec_meta["prepared_context"] = prep_ctx.model_dump()

            logger.info(
                "Graph node [prepare_review_context] completed: run_id=%s, duration=%.2fs",
                review_run_id,
                duration,
            )

            return {
                "status": "PREPARED",
                "diff_context_truncated": prep_ctx.diff_truncated,
                "execution_metadata": exec_meta,
            }

        except WorkflowError as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Graph node [prepare_review_context] failed: run_id=%s, category=%s, error=%s",
                review_run_id,
                exc.category.value,
                exc.message,
            )
            if self.raise_exceptions:
                raise

            return {
                "status": "FAILED",
                "error": exc.message,
                "error_category": exc.category.value,
            }

        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Graph node [prepare_review_context] encountered unexpected error: run_id=%s, error=%s",
                review_run_id,
                exc,
                exc_info=True,
            )
            if self.raise_exceptions:
                raise ContextPreparationError(
                    f"Unexpected context preparation error: {exc}"
                ) from exc

            return {
                "status": "FAILED",
                "error": str(exc),
                "error_category": WorkflowErrorCategory.CONTEXT_PREPARATION_FAILURE.value,
            }

    async def _planner_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 2: Invoke Planner Agent to generate grounded ReviewPlan."""
        start_time = time.monotonic()
        review_run_id = state.get("review_run_id", "unknown")

        logger.info(
            "Graph node [planner] started: run_id=%s",
            review_run_id,
        )

        try:
            exec_meta = dict(state.get("execution_metadata", {}))
            prep_ctx_data = exec_meta.get("prepared_context")

            if not prep_ctx_data:
                raise ContextPreparationError(
                    message="Planner node invoked without prepared_context in execution_metadata"
                )

            prep_ctx = PreparedPlannerContext.model_validate(prep_ctx_data)

            # Generate and validate ReviewPlan
            review_plan: ReviewPlan = await self.planner_agent.plan(prep_ctx)

            duration = time.monotonic() - start_time
            durations = dict(exec_meta.get("durations", {}))
            durations["planner_seconds"] = round(duration, 3)
            exec_meta["durations"] = durations

            tokens_used = review_plan.metadata.get("planner_total_tokens", 0)
            exec_meta["total_tokens"] = exec_meta.get("total_tokens", 0) + tokens_used

            logger.info(
                "Graph node [planner] completed: run_id=%s, scope=%s, active_agents=%s, duration=%.2fs",
                review_run_id,
                review_plan.review_scope,
                review_plan.active_agents,
                duration,
            )

            return {
                "status": "PLANNED",
                "review_plan": review_plan.model_dump(by_alias=True),
                "execution_metadata": exec_meta,
            }

        except WorkflowError as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Graph node [planner] failed: run_id=%s, category=%s, error=%s",
                review_run_id,
                exc.category.value,
                exc.message,
            )
            if self.raise_exceptions:
                raise

            return {
                "status": "FAILED",
                "error": exc.message,
                "error_category": exc.category.value,
            }

        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Graph node [planner] encountered unexpected error: run_id=%s, error=%s",
                review_run_id,
                exc,
                exc_info=True,
            )
            if self.raise_exceptions:
                raise

            return {
                "status": "FAILED",
                "error": str(exc),
                "error_category": WorkflowErrorCategory.INVALID_PLANNER_OUTPUT.value,
            }

    def _should_continue_to_planner(self, state: ReviewState) -> str:
        """Deterministic conditional router between context preparation and planning."""
        status = state.get("status")
        if status == "FAILED":
            logger.warning(
                "Aborting workflow prior to planner node due to state status=FAILED: error=%s",
                state.get("error"),
            )
            return END
        return "planner"

    def _route_specialists(self, state: ReviewState) -> list[str]:
        """Conditional fan-out router from Planner to active domain specialist agents."""
        status = state.get("status")
        if status == "FAILED":
            logger.warning(
                "Aborting workflow prior to specialist fan-out due to state status=FAILED: error=%s",
                state.get("error"),
            )
            return [END]

        plan = extract_review_plan(state)
        active_agents = plan.active_agents if plan else []

        selected_nodes = [
            agent for agent in active_agents if agent in KNOWN_SPECIALIST_AGENTS
        ]

        logger.info(
            "Planner routing to specialists: active_agents=%s, selected_nodes=%s",
            active_agents,
            selected_nodes,
        )

        if not selected_nodes:
            logger.info(
                "No active specialist agents selected; routing directly to aggregate_findings"
            )
            return ["aggregate_findings"]

        return selected_nodes

    async def _security_agent_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 3a: Execute Security Analysis Specialist Agent."""
        return await self.security_agent.execute_node(
            state, raise_exceptions=self.raise_exceptions
        )

    async def _bug_logic_agent_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 3b: Execute Bug & Logic Analysis Specialist Agent."""
        return await self.bug_logic_agent.execute_node(
            state, raise_exceptions=self.raise_exceptions
        )

    async def _error_handling_agent_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 3c: Execute Error Handling Specialist Agent."""
        return await self.error_handling_agent.execute_node(
            state, raise_exceptions=self.raise_exceptions
        )

    async def _test_adequacy_agent_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 3d: Execute Test Adequacy Specialist Agent."""
        return await self.test_adequacy_agent.execute_node(
            state, raise_exceptions=self.raise_exceptions
        )

    def _aggregate_findings_node(self, state: ReviewState) -> dict[str, Any]:
        """Node 4: Fan-in aggregation barrier gathering findings and failure telemetry."""
        start_time = time.monotonic()
        review_run_id = state.get("review_run_id", "unknown")
        raw_findings = state.get("candidate_findings", [])
        specialist_errors = state.get("specialist_errors", [])
        plan = extract_review_plan(state)
        active_agents = plan.active_agents if plan else []

        logger.info(
            "Graph node [aggregate_findings] started: run_id=%s, candidate_findings=%d, specialist_errors=%d",
            review_run_id,
            len(raw_findings),
            len(specialist_errors),
        )

        duration = time.monotonic() - start_time
        exec_meta = dict(state.get("execution_metadata", {}))
        durations = dict(exec_meta.get("durations", {}))
        durations["aggregate_findings_seconds"] = round(duration, 3)
        exec_meta["durations"] = durations
        exec_meta["candidate_findings_count"] = len(raw_findings)
        exec_meta["specialist_errors"] = specialist_errors

        # Record findings breakdown by specialist
        agent_counts: dict[str, int] = {}
        for f in raw_findings:
            agent = str(f.get("agent_name", "unknown"))
            agent_counts[agent] = agent_counts.get(agent, 0) + 1
        exec_meta["findings_by_agent"] = agent_counts

        # Determine failure status: fail only if all active agents failed and no findings exist
        all_failed = False
        if (
            active_agents
            and len(specialist_errors) >= len(active_agents)
            and not raw_findings
        ):
            all_failed = True

        if all_failed:
            first_err = specialist_errors[0] if specialist_errors else {}
            err_msg = first_err.get("error", "All active specialist agents failed")
            err_cat = first_err.get(
                "error_category", WorkflowErrorCategory.WORKFLOW_EXECUTION_FAILURE.value
            )
            logger.error(
                "Graph node [aggregate_findings] completed with all specialists failing: run_id=%s, error=%s",
                review_run_id,
                err_msg,
            )
            return {
                "status": "FAILED",
                "error": err_msg,
                "error_category": err_cat,
                "execution_metadata": exec_meta,
            }

        logger.info(
            "Graph node [aggregate_findings] completed: run_id=%s, candidate_findings=%d, duration=%.2fs",
            review_run_id,
            len(raw_findings),
            duration,
        )

        return {
            "status": "CANDIDATES_AGGREGATED",
            "execution_metadata": exec_meta,
        }

    def _route_verification(self, state: ReviewState) -> list[Any]:
        """Conditional router from candidate aggregation to parallel Critic verification."""
        status = state.get("status")
        if status == "FAILED":
            logger.warning(
                "Aborting workflow prior to verification due to state status=FAILED: error=%s",
                state.get("error"),
            )
            return [END]

        candidates = extract_candidate_findings(state)
        if not candidates:
            logger.info(
                "No candidate findings to verify; routing directly to aggregate_verification"
            )
            return ["aggregate_verification"]

        logger.info(
            "Routing %d candidate findings to parallel Critic verification",
            len(candidates),
        )
        exec_meta = dict(state.get("execution_metadata", {}))
        prep_data = exec_meta.get("prepared_context")
        prep_dict: dict[str, Any] = prep_data if isinstance(prep_data, dict) else {}
        parsed_diff = state.get("parsed_diff") or prep_dict.get("parsed_diff")
        changed_files = state.get("changed_files") or prep_dict.get("changed_files", [])
        evidence_items = state.get("evidence_items") or prep_dict.get(
            "evidence_items", []
        )
        review_run_id = state.get("review_run_id", "unknown")
        repo_name = state.get("repository_full_name", "")
        commit_sha = state.get("commit_sha", "")
        base_sha = state.get("base_sha")

        sends: list[Any] = []
        for finding in candidates:
            payload = {
                "candidate_finding": finding.model_dump(by_alias=True),
                "parsed_diff": parsed_diff,
                "changed_files": changed_files,
                "evidence_items": evidence_items,
                "review_run_id": review_run_id,
                "repository_full_name": repo_name,
                "commit_sha": commit_sha,
                "base_sha": base_sha,
            }
            sends.append(Send("verify_candidate_finding", payload))
        return sends

    async def _verify_candidate_finding_node(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Node: Verify a single candidate finding using CriticAgent with deterministic grounding."""
        raw_finding = payload.get("candidate_finding", {})
        try:
            finding = ReviewFinding.model_validate(raw_finding)
        except Exception as exc:
            return {
                "verification_errors": [
                    {
                        "finding_id": str(raw_finding.get("finding_id") or "unknown"),
                        "error": f"Failed to deserialize candidate finding: {exc}",
                        "retryable": False,
                    }
                ]
            }

        parsed_diff_raw = payload.get("parsed_diff")
        parsed_diff: ParsedDiff | None = None
        if parsed_diff_raw:
            with contextlib.suppress(Exception):
                parsed_diff = ParsedDiff.model_validate(parsed_diff_raw)

        try:
            result = await self.critic_agent.verify_candidate(
                finding=finding,
                parsed_diff=parsed_diff,
                changed_files=payload.get("changed_files", []),
                review_run_id=payload.get("review_run_id", "unknown"),
                repository_full_name=payload.get("repository_full_name", ""),
                commit_sha=payload.get("commit_sha", ""),
                base_sha=payload.get("base_sha"),
                evidence_items=payload.get("evidence_items", []),
            )

            self.grounding_service.apply_verification_to_finding(finding, result)
            finding_dict = finding.model_dump(by_alias=True)
            result_dict = result.model_dump(by_alias=True)

            if result.is_verified:
                return {
                    "verified_findings": [finding_dict],
                    "verification_results": [result_dict],
                }
            else:
                return {
                    "rejected_findings": [finding_dict],
                    "verification_results": [result_dict],
                }

        except (LLMTimeoutError, LLMProviderError) as exc:
            logger.error(
                "Critic verification encountered transient error for finding %s: %s",
                finding.finding_id,
                exc,
            )
            return {
                "verification_errors": [
                    {
                        "finding_id": str(finding.finding_id),
                        "error": exc.message,
                        "error_category": exc.category.value,
                        "retryable": exc.retryable,
                    }
                ]
            }
        except Exception as exc:
            logger.error(
                "Critic verification failed for finding %s: %s",
                finding.finding_id,
                exc,
                exc_info=True,
            )
            return {
                "verification_errors": [
                    {
                        "finding_id": str(finding.finding_id),
                        "error": str(exc),
                        "error_category": WorkflowErrorCategory.INVALID_CRITIC_OUTPUT.value,
                        "retryable": False,
                    }
                ]
            }

    def _aggregate_verification_node(self, state: ReviewState) -> dict[str, Any]:
        """Node: Aggregate verified, rejected, and error records from all Critic evaluations."""
        start_time = time.monotonic()
        review_run_id = state.get("review_run_id", "unknown")

        candidates = extract_candidate_findings(state)
        verified = extract_verified_findings(state)
        rejected = extract_rejected_findings(state)
        errors = state.get("verification_errors", [])

        candidate_count = len(candidates)
        verified_count = len(verified)
        rejected_count = len(rejected)
        error_count = len(errors)

        reduction_rate = (
            round((rejected_count / candidate_count) * 100, 2)
            if candidate_count > 0
            else 0.0
        )

        duration = time.monotonic() - start_time
        exec_meta = dict(state.get("execution_metadata", {}))
        durations = dict(exec_meta.get("durations", {}))
        durations["aggregate_verification_seconds"] = round(duration, 3)
        exec_meta["durations"] = durations

        exec_meta["candidate_findings_count"] = candidate_count
        exec_meta["verified_findings_count"] = verified_count
        exec_meta["rejected_findings_count"] = rejected_count
        exec_meta["verification_errors_count"] = error_count
        exec_meta["false_positive_reduction_rate"] = reduction_rate

        logger.info(
            "Graph node [aggregate_verification] completed: run_id=%s, candidates=%d, verified=%d, rejected=%d, errors=%d, reduction=%.1f%%, duration=%.2fs",
            review_run_id,
            candidate_count,
            verified_count,
            rejected_count,
            error_count,
            reduction_rate,
            duration,
        )

        return {
            "status": "COMPLETED",
            "execution_metadata": exec_meta,
        }

    def build(self) -> CompiledStateGraph:
        """Construct, wire, and compile the review StateGraph."""
        builder = StateGraph(ReviewState)

        # 1. Register Nodes
        builder.add_node("prepare_review_context", self._prepare_review_context_node)
        builder.add_node("planner", self._planner_node)
        builder.add_node("security_agent", self._security_agent_node)
        builder.add_node("bug_logic_agent", self._bug_logic_agent_node)
        builder.add_node("error_handling_agent", self._error_handling_agent_node)
        builder.add_node("test_adequacy_agent", self._test_adequacy_agent_node)
        builder.add_node("aggregate_findings", self._aggregate_findings_node)
        builder.add_node(
            "verify_candidate_finding", cast(Any, self._verify_candidate_finding_node)
        )
        builder.add_node("aggregate_verification", self._aggregate_verification_node)

        # 2. Register Edges and Conditional Transitions
        builder.add_edge(START, "prepare_review_context")
        builder.add_conditional_edges(
            "prepare_review_context",
            self._should_continue_to_planner,
            {
                "planner": "planner",
                END: END,
            },
        )

        # Planner conditional fan-out
        builder.add_conditional_edges(
            "planner",
            self._route_specialists,
            [
                "security_agent",
                "bug_logic_agent",
                "error_handling_agent",
                "test_adequacy_agent",
                "aggregate_findings",
                END,
            ],
        )

        # Parallel fan-in edges to candidate aggregation node
        builder.add_edge("security_agent", "aggregate_findings")
        builder.add_edge("bug_logic_agent", "aggregate_findings")
        builder.add_edge("error_handling_agent", "aggregate_findings")
        builder.add_edge("test_adequacy_agent", "aggregate_findings")

        # Candidate aggregation routes to verification
        builder.add_conditional_edges(
            "aggregate_findings",
            self._route_verification,
            [
                "verify_candidate_finding",
                "aggregate_verification",
                END,
            ],
        )

        # Parallel Critic fan-in edges to verification aggregation
        builder.add_edge("verify_candidate_finding", "aggregate_verification")
        builder.add_edge("aggregate_verification", END)

        # 3. Compile Graph with Checkpointer
        compiled_graph = builder.compile(checkpointer=self.checkpointer)
        return compiled_graph


def create_review_graph(
    planner_agent: PlannerAgent | None = None,
    security_agent: SecurityAgent | None = None,
    bug_logic_agent: BugLogicAgent | None = None,
    error_handling_agent: ErrorHandlingAgent | None = None,
    test_adequacy_agent: TestAdequacyAgent | None = None,
    critic_agent: CriticAgent | None = None,
    grounding_service: EvidenceGroundingService | None = None,
    context_builder: PlannerContextBuilder | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    raise_exceptions: bool = False,
) -> CompiledStateGraph:
    """Factory helper to construct and compile a ready-to-execute review StateGraph."""
    graph_builder = ReviewGraphBuilder(
        planner_agent=planner_agent,
        security_agent=security_agent,
        bug_logic_agent=bug_logic_agent,
        error_handling_agent=error_handling_agent,
        test_adequacy_agent=test_adequacy_agent,
        critic_agent=critic_agent,
        grounding_service=grounding_service,
        context_builder=context_builder,
        checkpointer=checkpointer,
        raise_exceptions=raise_exceptions,
    )
    return graph_builder.build()


async def execute_review_graph(
    initial_state: ReviewState,
    graph: CompiledStateGraph | None = None,
    planner_agent: PlannerAgent | None = None,
    security_agent: SecurityAgent | None = None,
    bug_logic_agent: BugLogicAgent | None = None,
    error_handling_agent: ErrorHandlingAgent | None = None,
    test_adequacy_agent: TestAdequacyAgent | None = None,
    critic_agent: CriticAgent | None = None,
    grounding_service: EvidenceGroundingService | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    raise_on_failure: bool = False,
) -> ReviewState:
    """High-level execution runner for the review workflow graph.

    Configures checkpoint thread identity using review_run_id and executes
    the graph asynchronously to completion.
    """
    review_run_id = initial_state.get("review_run_id", "default_run")
    config = get_thread_config(review_run_id)

    target_graph = graph or create_review_graph(
        planner_agent=planner_agent,
        security_agent=security_agent,
        bug_logic_agent=bug_logic_agent,
        error_handling_agent=error_handling_agent,
        test_adequacy_agent=test_adequacy_agent,
        critic_agent=critic_agent,
        grounding_service=grounding_service,
        checkpointer=checkpointer,
        raise_exceptions=raise_on_failure,
    )

    result_state = cast(
        ReviewState, await target_graph.ainvoke(initial_state, config=config)
    )

    if raise_on_failure and result_state.get("status") == "FAILED":
        error_msg = result_state.get("error") or "Workflow execution failed"
        error_cat_raw = (
            result_state.get("error_category")
            or WorkflowErrorCategory.WORKFLOW_EXECUTION_FAILURE.value
        )
        try:
            error_cat = WorkflowErrorCategory(error_cat_raw)
        except ValueError:
            error_cat = WorkflowErrorCategory.WORKFLOW_EXECUTION_FAILURE
        raise WorkflowError(
            message=error_msg,
            category=error_cat,
            retryable=False,
        )

    return result_state
