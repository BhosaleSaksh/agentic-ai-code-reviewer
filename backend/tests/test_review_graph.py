"""Integration and execution tests for the LangGraph review StateGraph workflow."""

from typing import cast

import pytest
from app.agents.planner import PlannerAgent
from app.orchestration.checkpoint import create_checkpointer, get_thread_config
from app.orchestration.errors import (
    EvidenceValidationError,
    InvalidPlannerOutputError,
    LLMTimeoutError,
    WorkflowError,
)
from app.orchestration.review_graph import (
    ReviewGraphBuilder,
    create_review_graph,
    execute_review_graph,
)
from app.orchestration.state import (
    ReviewState,
    create_initial_review_state,
    extract_review_plan,
)
from app.schemas.enums import EvidenceType
from app.schemas.evidence import EvidenceModel
from app.schemas.review_plan import ReviewPlan
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService


@pytest.fixture
def mock_review_plan() -> ReviewPlan:
    return ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
        focus_areas=["Authentication", "Error handling"],
        target_files=["backend/app/auth.py"],
        reasoning="Authentication modifications require security agent inspection.",
    )


@pytest.fixture
def sample_initial_state() -> ReviewState:
    evidence = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=10,
        end_line=12,
        snippet="password = 'secret'",
        corroborating_tool="semgrep",
        rule_or_cve_id="hardcoded-secret",
    )
    return create_initial_review_state(
        review_run_id="run-test-graph-01",
        repository_id=10,
        repository_full_name="owner/repo",
        pr_number=5,
        commit_sha="a" * 40,
        base_sha="b" * 40,
        pr_title="Refactor Auth Layer",
        pr_author="octocat",
        changed_files=["backend/app/auth.py"],
        evidence_items=[evidence],
    )


@pytest.mark.asyncio
async def test_review_graph_happy_path(
    sample_initial_state: ReviewState, mock_review_plan: ReviewPlan
) -> None:
    """Verify end-to-end execution: START -> prepare_review_context -> planner -> END."""
    provider = MockLLMProvider(default_response=mock_review_plan)
    planner = PlannerAgent(llm_service=LLMService(provider=provider))
    checkpointer = create_checkpointer()

    graph = create_review_graph(
        planner_agent=planner,
        checkpointer=checkpointer,
    )

    thread_config = get_thread_config(sample_initial_state["review_run_id"])
    final_state = cast(
        ReviewState,
        await graph.ainvoke(sample_initial_state, config=thread_config),
    )

    # 1. Status verification
    assert final_state["status"] == "COMPLETED"
    assert final_state["error"] is None

    # 2. Plan verification
    plan = extract_review_plan(final_state)
    assert plan is not None
    assert plan.review_scope == "FULL"
    assert "security_agent" in plan.active_agents

    # 3. Context & Telemetry verification
    exec_meta = final_state["execution_metadata"]
    assert "prepare_context_seconds" in exec_meta["durations"]
    assert "planner_seconds" in exec_meta["durations"]
    assert exec_meta["total_tokens"] > 0

    # 4. State identity preservation
    assert final_state["review_run_id"] == "run-test-graph-01"
    assert final_state["commit_sha"] == "a" * 40


@pytest.mark.asyncio
async def test_review_graph_checkpoint_retrieval(
    sample_initial_state: ReviewState, mock_review_plan: ReviewPlan
) -> None:
    """Verify that execution checkpoints are retrievable using review_run_id thread config."""
    provider = MockLLMProvider(default_response=mock_review_plan)
    planner = PlannerAgent(llm_service=LLMService(provider=provider))
    checkpointer = create_checkpointer()

    graph = create_review_graph(
        planner_agent=planner,
        checkpointer=checkpointer,
    )

    thread_config = get_thread_config("run-checkpoint-test")
    sample_initial_state["review_run_id"] = "run-checkpoint-test"

    await graph.ainvoke(sample_initial_state, config=thread_config)

    # Inspect checkpoint from graph state snapshot and checkpointer tuple
    state_snapshot = graph.get_state(thread_config)
    assert state_snapshot is not None
    assert state_snapshot.values["status"] == "COMPLETED"
    assert state_snapshot.values["review_run_id"] == "run-checkpoint-test"

    checkpoint_tuple = checkpointer.get_tuple(thread_config)
    assert checkpoint_tuple is not None


@pytest.mark.asyncio
async def test_review_graph_aborts_on_context_preparation_failure() -> None:
    """Verify conditional transition halts at END if context preparation fails."""
    # Stale evidence from a different commit SHA
    stale_evidence = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=1,
        end_line=2,
        snippet="snippet",
        metadata={"commit_sha": "d" * 40},
    )

    state = create_initial_review_state(
        review_run_id="run-fail-ctx",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=1,
        commit_sha="a" * 40,
        evidence_items=[stale_evidence],
    )

    provider = MockLLMProvider()
    planner = PlannerAgent(llm_service=LLMService(provider=provider))
    graph = create_review_graph(planner_agent=planner)

    final_state = cast(
        ReviewState,
        await graph.ainvoke(state, config=get_thread_config("run-fail-ctx")),
    )

    assert final_state["status"] == "FAILED"
    assert final_state["error_category"] == "EVIDENCE_VALIDATION_FAILURE"
    # Planner node should never have been called
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_review_graph_handles_planner_llm_timeout(
    sample_initial_state: ReviewState,
) -> None:
    """Verify graph handles transient LLM timeout gracefully, marking state FAILED."""
    provider = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Provider timed out", timeout_seconds=5.0)
    )
    planner = PlannerAgent(llm_service=LLMService(provider=provider))
    graph = create_review_graph(planner_agent=planner)

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            sample_initial_state, config=get_thread_config("run-timeout")
        ),
    )

    assert final_state["status"] == "FAILED"
    assert final_state["error_category"] == "LLM_TIMEOUT"
    assert "Provider timed out" in str(final_state["error"])


@pytest.mark.asyncio
async def test_review_graph_handles_invalid_planner_output(
    sample_initial_state: ReviewState,
) -> None:
    """Verify graph handles malformed structured output, marking state FAILED."""
    provider = MockLLMProvider(default_response="not json at all")
    planner = PlannerAgent(llm_service=LLMService(provider=provider))
    graph = create_review_graph(planner_agent=planner)

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            sample_initial_state, config=get_thread_config("run-invalid-output")
        ),
    )

    assert final_state["status"] == "FAILED"
    assert final_state["error_category"] == "INVALID_PLANNER_OUTPUT"


@pytest.mark.asyncio
async def test_execute_review_graph_runner_with_raise_on_failure(
    sample_initial_state: ReviewState,
) -> None:
    """Verify execute_review_graph helper re-raises when raise_on_failure=True."""
    provider = MockLLMProvider(
        should_raise=InvalidPlannerOutputError(message="Invalid schema")
    )
    planner = PlannerAgent(llm_service=LLMService(provider=provider))
    with pytest.raises(WorkflowError):
        await execute_review_graph(
            sample_initial_state,
            planner_agent=planner,
            raise_on_failure=True,
        )


@pytest.mark.asyncio
async def test_review_graph_missing_commit_sha() -> None:
    """Verify graph handles missing commit_sha with EVIDENCE_VALIDATION_FAILURE."""
    state = create_initial_review_state(
        review_run_id="run-missing-sha",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=1,
        commit_sha="a" * 40,
    )
    # Manually remove commit_sha from state
    state["commit_sha"] = ""

    graph = create_review_graph()
    final_state = cast(
        ReviewState,
        await graph.ainvoke(state, config=get_thread_config("run-missing-sha")),
    )

    assert final_state["status"] == "FAILED"
    assert final_state["error_category"] == "EVIDENCE_VALIDATION_FAILURE"


@pytest.mark.asyncio
async def test_review_graph_node_raise_exceptions_flag() -> None:
    """Verify ReviewGraphBuilder re-raises when raise_exceptions=True."""
    state = create_initial_review_state(
        review_run_id="run-raise",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=1,
        commit_sha="a" * 40,
    )
    state["commit_sha"] = ""

    graph = create_review_graph(raise_exceptions=True)

    with pytest.raises(EvidenceValidationError):
        await graph.ainvoke(state, config=get_thread_config("run-raise"))


@pytest.mark.asyncio
async def test_review_graph_planner_node_missing_prepared_context() -> None:
    """Verify planner node fails cleanly if prepared_context is missing."""
    builder = ReviewGraphBuilder()
    empty_state: ReviewState = {
        "review_run_id": "run-empty",
        "status": "PREPARED",
        "execution_metadata": {},
    }

    result = await builder._planner_node(empty_state)
    assert result["status"] == "FAILED"
    assert result["error_category"] == "CONTEXT_PREPARATION_FAILURE"
