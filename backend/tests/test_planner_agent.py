"""Unit tests for PlannerAgent execution, validation, and evidence grounding."""

import pytest
from app.agents.planner import PlannerAgent
from app.orchestration.context_builder import PreparedPlannerContext
from app.orchestration.errors import (
    InvalidPlannerOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.review_plan import ReviewPlan
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService


@pytest.fixture
def sample_context() -> PreparedPlannerContext:
    return PreparedPlannerContext(
        pr_title="Add Payment Gateway",
        pr_author="dave",
        commit_sha="a" * 40,
        base_sha="b" * 40,
        repository_full_name="owner/repo",
        changed_files=["app/payment.py", "app/routes.py"],
        total_files=2,
        total_additions=120,
        total_deletions=10,
        is_large_pr=False,
        chunking_strategy="NONE",
        file_chunks=[["app/payment.py", "app/routes.py"]],
        evidence_items=[
            {
                "corroborating_tool": "semgrep",
                "rule_or_cve_id": "payment.insecure-http",
                "file_path": "app/payment.py",
                "start_line": 15,
                "end_line": 18,
                "content_snippet": "http.get(url)",
            }
        ],
        evidence_summary={"semgrep": 1},
        evidence_items_total=1,
        evidence_items_included=1,
        evidence_truncated=False,
        formatted_diff="+++ b/app/payment.py\n+http.get(url)",
        diff_lines_total=1,
        diff_lines_included=1,
        diff_bytes=30,
        diff_truncated=False,
    )


@pytest.mark.asyncio
async def test_planner_agent_generates_valid_plan(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify PlannerAgent generates and returns a validated ReviewPlan."""
    mock_plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
        focus_areas=["Payment Security", "Input Validation"],
        target_files=["app/payment.py"],
        reasoning="Payment processing requires rigorous security and logic review.",
    )
    provider = MockLLMProvider(default_response=mock_plan)
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    plan = await agent.plan(sample_context)

    assert plan.review_scope == "FULL"
    assert "security_agent" in plan.active_agents
    assert "bug_logic_agent" in plan.active_agents
    assert "Payment Security" in plan.focus_areas
    assert "planner_duration_seconds" in plan.metadata
    assert plan.metadata["planner_prompt_version"] == "1.0.0"


@pytest.mark.asyncio
async def test_planner_agent_enforces_evidence_first_security_agent(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify that if deterministic security evidence exists, security_agent is enforced."""
    # LLM omits security_agent despite Semgrep evidence in sample_context
    omitted_plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["bug_logic_agent"],
        focus_areas=["General review"],
    )
    provider = MockLLMProvider(default_response=omitted_plan)
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    plan = await agent.plan(sample_context)

    # security_agent must be injected due to evidence-first principle
    assert "security_agent" in plan.active_agents


@pytest.mark.asyncio
async def test_planner_agent_filters_unknown_agents(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify that hallucinated agent names not in KNOWN_SPECIALIST_AGENTS are dropped."""
    plan_with_hallucination = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "hallucinated_agent_xyz", "bug_logic_agent"],
    )
    provider = MockLLMProvider(default_response=plan_with_hallucination)
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    plan = await agent.plan(sample_context)

    assert "hallucinated_agent_xyz" not in plan.active_agents
    assert "security_agent" in plan.active_agents
    assert "bug_logic_agent" in plan.active_agents


@pytest.mark.asyncio
async def test_planner_agent_defaults_empty_target_files(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify that if target_files is empty, it defaults to changed files in context."""
    plan_empty_files = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        target_files=[],
    )
    provider = MockLLMProvider(default_response=plan_empty_files)
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    plan = await agent.plan(sample_context)

    assert plan.target_files == ["app/payment.py", "app/routes.py"]


@pytest.mark.asyncio
async def test_planner_agent_handles_timeout(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify PlannerAgent raises LLMTimeoutError on timeout."""
    provider = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Timed out", timeout_seconds=1.0)
    )
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(LLMTimeoutError):
        await agent.plan(sample_context)


@pytest.mark.asyncio
async def test_planner_agent_handles_provider_failure(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify PlannerAgent raises LLMProviderError on external service error."""
    provider = MockLLMProvider(
        should_raise=LLMProviderError(message="500 Internal Error", status_code=500)
    )
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(LLMProviderError):
        await agent.plan(sample_context)


@pytest.mark.asyncio
async def test_planner_agent_handles_malformed_output(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify PlannerAgent raises InvalidPlannerOutputError on malformed response."""
    provider = MockLLMProvider(default_response="not a valid json object")
    agent = PlannerAgent(llm_service=LLMService(provider=provider))
    with pytest.raises(InvalidPlannerOutputError):
        await agent.plan(sample_context)


@pytest.mark.asyncio
async def test_planner_agent_large_pr_chunking_fallback(
    sample_context: PreparedPlannerContext,
) -> None:
    """Verify PlannerAgent assigns FILE_MODULE and file_chunks when is_large_pr is True."""
    # Modify context to be large PR
    large_ctx = PreparedPlannerContext(
        pr_title=sample_context.pr_title,
        pr_author=sample_context.pr_author,
        commit_sha=sample_context.commit_sha,
        base_sha=sample_context.base_sha,
        repository_full_name=sample_context.repository_full_name,
        changed_files=sample_context.changed_files,
        total_files=sample_context.total_files,
        total_additions=500,
        total_deletions=200,
        is_large_pr=True,
        chunking_strategy="FILE_MODULE",
        file_chunks=[["app/payment.py"], ["app/routes.py"]],
        evidence_items=[],
        evidence_summary={},
        evidence_items_total=0,
        evidence_items_included=0,
        evidence_truncated=False,
        formatted_diff="+++ b/app/payment.py",
        diff_lines_total=1,
        diff_lines_included=1,
        diff_bytes=20,
        diff_truncated=False,
    )

    # LLM omits chunking strategy
    plan_missing_chunks = ReviewPlan(
        review_scope="FULL",
        active_agents=["bug_logic_agent"],
        is_large_pr=True,
        chunking_strategy=None,
        file_chunks=[],
    )
    provider = MockLLMProvider(default_response=plan_missing_chunks)
    agent = PlannerAgent(llm_service=LLMService(provider=provider))

    plan = await agent.plan(large_ctx)
    assert plan.chunking_strategy == "FILE_MODULE"
    assert len(plan.file_chunks) == 2


@pytest.mark.asyncio
async def test_planner_agent_unexpected_exception(
    sample_context: PreparedPlannerContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify PlannerAgent wraps unexpected generation exceptions in InvalidPlannerOutputError."""
    agent = PlannerAgent(llm_service=LLMService(provider=MockLLMProvider()))

    async def _failing_generate(*_args: object, **_kwargs: object) -> object:
        raise ZeroDivisionError("math error")

    monkeypatch.setattr(agent.llm_service, "generate_structured", _failing_generate)

    with pytest.raises(InvalidPlannerOutputError, match="Planner agent failure"):
        await agent.plan(sample_context)
