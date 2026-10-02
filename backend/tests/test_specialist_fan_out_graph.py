"""Integration and fan-out tests for Planner -> Specialist -> Aggregation LangGraph workflow."""

from typing import cast

import pytest
from app.agents.bug_logic import BugLogicAgent
from app.agents.error_handling import ErrorHandlingAgent
from app.agents.planner import PlannerAgent
from app.agents.security import SecurityAgent
from app.agents.test_adequacy import TestAdequacyAgent
from app.orchestration.checkpoint import get_thread_config
from app.orchestration.errors import (
    LLMTimeoutError,
)
from app.orchestration.review_graph import (
    create_review_graph,
    execute_review_graph,
)
from app.orchestration.state import (
    ReviewState,
    create_initial_review_state,
    extract_candidate_findings,
)
from app.schemas.enums import (
    EvidenceType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService


@pytest.fixture
def initial_state_with_evidence() -> ReviewState:
    ev = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="backend/app/auth.py",
        start_line=10,
        end_line=12,
        snippet="token = os.environ.get('SECRET')",
        corroborating_tool="semgrep",
        rule_or_cve_id="hardcoded-secret",
    )
    return create_initial_review_state(
        review_run_id="run-fan-out-01",
        repository_id=5,
        repository_full_name="owner/repo",
        pr_number=42,
        commit_sha="a" * 40,
        base_sha="b" * 40,
        pr_title="Add Auth Layer",
        pr_author="octocat",
        changed_files=["backend/app/auth.py", "backend/app/db.py"],
        evidence_items=[ev],
    )


def make_mock_finding(
    agent_name: str,
    issue_type: IssueType,
    file_path: str,
    line_number: int,
    title: str,
    severity: Severity = Severity.HIGH,
) -> ReviewFinding:
    return ReviewFinding(
        issue_type=issue_type,
        severity=severity,
        affected_file=file_path,
        line_number=line_number,
        side=FindingSide.RIGHT,
        title=title,
        explanation=f"Explanation for {title} in {file_path}",
        recommendation=f"Remediate {title}",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path=file_path,
                start_line=line_number,
                end_line=line_number,
                snippet=f"+ line {line_number} code",
            )
        ],
        agent_name=agent_name,
        raw_confidence=0.9,
    )


@pytest.mark.asyncio
async def test_fan_out_routes_only_to_scoped_agents(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify that only the specialists declared in ReviewPlan.active_agents are executed."""
    # Plan activates ONLY security_agent
    plan = ReviewPlan(
        review_scope="SECURITY_ONLY",
        active_agents=["security_agent"],
        focus_areas=["Secrets"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_finding = make_mock_finding(
        "security_agent",
        IssueType.SECURITY,
        "backend/app/auth.py",
        10,
        "Secret finding",
    )
    sec_provider = MockLLMProvider(default_response=[sec_finding])

    # Other providers set to record calls
    bug_provider = MockLLMProvider()
    err_provider = MockLLMProvider()
    test_provider = MockLLMProvider()

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_provider)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_provider)),
        error_handling_agent=ErrorHandlingAgent(
            llm_service=LLMService(provider=err_provider)
        ),
        test_adequacy_agent=TestAdequacyAgent(
            llm_service=LLMService(provider=test_provider)
        ),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state_with_evidence,
            config=get_thread_config(initial_state_with_evidence["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    # Security was called
    assert sec_provider.call_count == 1
    # Other agents were scoped out and NEVER called
    assert bug_provider.call_count == 0
    assert err_provider.call_count == 0
    assert test_provider.call_count == 0

    findings = extract_candidate_findings(final_state)
    assert len(findings) == 1
    assert findings[0].title == "Secret finding"
    assert findings[0].agent_name == "security_agent"


@pytest.mark.asyncio
async def test_fan_out_multiple_specialists_execution(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify multiple active specialists execute in parallel and collect all findings."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent", "error_handling_agent"],
        focus_areas=["Full audit"],
        target_files=["backend/app/auth.py"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_f = make_mock_finding(
        "security_agent", IssueType.SECURITY, "backend/app/auth.py", 10, "Sec issue"
    )
    bug_f = make_mock_finding(
        "bug_logic_agent", IssueType.BUG_LOGIC, "backend/app/auth.py", 15, "Bug issue"
    )
    err_f = make_mock_finding(
        "error_handling_agent",
        IssueType.ERROR_HANDLING,
        "backend/app/auth.py",
        20,
        "Error issue",
    )

    sec_p = MockLLMProvider(default_response=[sec_f])
    bug_p = MockLLMProvider(default_response=[bug_f])
    err_p = MockLLMProvider(default_response=[err_f])
    test_p = MockLLMProvider()

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_p)),
        error_handling_agent=ErrorHandlingAgent(llm_service=LLMService(provider=err_p)),
        test_adequacy_agent=TestAdequacyAgent(llm_service=LLMService(provider=test_p)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state_with_evidence,
            config=get_thread_config(initial_state_with_evidence["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    assert sec_p.call_count == 1
    assert bug_p.call_count == 1
    assert err_p.call_count == 1
    assert test_p.call_count == 0

    findings = extract_candidate_findings(final_state)
    assert len(findings) == 3
    agent_names = {f.agent_name for f in findings}
    assert agent_names == {"security_agent", "bug_logic_agent", "error_handling_agent"}
    assert all(f.verification_status == VerificationStatus.UNVERIFIED for f in findings)


@pytest.mark.asyncio
async def test_specialist_failure_isolation_transient_timeout(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify that a timeout in one specialist does NOT destroy results from successful specialists."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
    )
    planner_provider = MockLLMProvider(default_response=plan)
    sec_f = make_mock_finding(
        "security_agent", IssueType.SECURITY, "backend/app/auth.py", 10, "Sec finding"
    )
    sec_p = MockLLMProvider(default_response=[sec_f])
    # BugLogic encounters transient timeout
    bug_p = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Bug logic timed out", timeout_seconds=2.0)
    )

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_provider)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_p)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state_with_evidence,
            config=get_thread_config(initial_state_with_evidence["review_run_id"]),
        ),
    )

    # Workflow finishes with status COMPLETED because security_agent succeeded
    assert final_state["status"] == "COMPLETED"
    # Security findings preserved
    findings = extract_candidate_findings(final_state)
    assert len(findings) == 1
    assert findings[0].title == "Sec finding"

    # Specialist error is recorded with retryable classification
    spec_errors = final_state["specialist_errors"]
    assert len(spec_errors) == 1
    assert spec_errors[0]["agent_name"] == "bug_logic_agent"
    assert spec_errors[0]["retryable"] is True
    assert spec_errors[0]["error_category"] == "LLM_TIMEOUT"


@pytest.mark.asyncio
async def test_specialist_failure_isolation_non_retryable_malformed(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify non-retryable malformed output in one agent preserves other agent findings."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
    )
    planner_p = MockLLMProvider(default_response=plan)
    sec_f = make_mock_finding(
        "security_agent", IssueType.SECURITY, "backend/app/auth.py", 10, "Valid finding"
    )
    sec_p = MockLLMProvider(default_response=[sec_f])
    # Bug logic returns non-JSON string
    bug_p = MockLLMProvider(default_response="MALFORMED_NON_JSON")

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_p)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_p)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state_with_evidence,
            config=get_thread_config(initial_state_with_evidence["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    findings = extract_candidate_findings(final_state)
    assert len(findings) == 1
    assert findings[0].title == "Valid finding"

    spec_errors = final_state["specialist_errors"]
    assert len(spec_errors) == 1
    assert spec_errors[0]["agent_name"] == "bug_logic_agent"
    assert spec_errors[0]["retryable"] is False
    assert spec_errors[0]["error_category"] == "INVALID_SPECIALIST_OUTPUT"


@pytest.mark.asyncio
async def test_all_specialists_failing_marks_state_failed(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify that if all active specialists fail and no findings exist, graph status is FAILED."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
    )
    planner_p = MockLLMProvider(default_response=plan)
    sec_p = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Sec timeout", timeout_seconds=1.0)
    )
    bug_p = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Bug timeout", timeout_seconds=1.0)
    )

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_p)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_p)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state_with_evidence,
            config=get_thread_config(initial_state_with_evidence["review_run_id"]),
        ),
    )

    assert final_state["status"] == "FAILED"
    assert len(final_state["specialist_errors"]) == 2
    assert final_state["error"] is not None


@pytest.mark.asyncio
async def test_duplicate_candidate_finding_handling(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify that identical candidate findings across agents are cleanly deduplicated."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
    )
    planner_p = MockLLMProvider(default_response=plan)
    # Identical findings on same file, line, and title
    duplicate_title = "Input Validation Bypass"
    sec_f = make_mock_finding(
        "security_agent", IssueType.SECURITY, "backend/app/auth.py", 25, duplicate_title
    )
    bug_f = make_mock_finding(
        "bug_logic_agent",
        IssueType.BUG_LOGIC,
        "backend/app/auth.py",
        25,
        duplicate_title,
    )

    sec_p = MockLLMProvider(default_response=[sec_f])
    bug_p = MockLLMProvider(default_response=[bug_f])

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_p)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
        bug_logic_agent=BugLogicAgent(llm_service=LLMService(provider=bug_p)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state_with_evidence,
            config=get_thread_config(initial_state_with_evidence["review_run_id"]),
        ),
    )

    findings = extract_candidate_findings(final_state)
    # Deduplication ensures only 1 unique finding for that semantic coordinate
    assert len(findings) == 1
    assert findings[0].title == duplicate_title


@pytest.mark.asyncio
async def test_zero_active_agents_routes_to_aggregation() -> None:
    """Verify that when ReviewPlan has 0 active agents, graph routes directly to aggregation."""
    initial_state = create_initial_review_state(
        review_run_id="run-zero-active-01",
        repository_id=5,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        commit_sha="a" * 40,
        base_sha="b" * 40,
        pr_title="Documentation only update",
        pr_author="octocat",
        changed_files=[],
        evidence_items=[],
    )
    plan = ReviewPlan(
        review_scope="TRIVIAL",
        active_agents=[],  # No specialists
        reasoning="Documentation only changes.",
    )
    planner_p = MockLLMProvider(default_response=plan)
    sec_p = MockLLMProvider()

    graph = create_review_graph(
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_p)),
        security_agent=SecurityAgent(llm_service=LLMService(provider=sec_p)),
    )

    final_state = cast(
        ReviewState,
        await graph.ainvoke(
            initial_state,
            config=get_thread_config(initial_state["review_run_id"]),
        ),
    )

    assert final_state["status"] == "COMPLETED"
    assert sec_p.call_count == 0
    assert len(extract_candidate_findings(final_state)) == 0


@pytest.mark.asyncio
async def test_execute_review_graph_high_level_runner(
    initial_state_with_evidence: ReviewState,
) -> None:
    """Verify execute_review_graph runner executes end-to-end with injected specialists."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["test_adequacy_agent"],
    )
    planner_p = MockLLMProvider(default_response=plan)
    test_f = make_mock_finding(
        "test_adequacy_agent",
        IssueType.TEST_ADEQUACY,
        "backend/app/auth.py",
        10,
        "Missing test",
    )
    test_p = MockLLMProvider(default_response=[test_f])

    result = await execute_review_graph(
        initial_state=initial_state_with_evidence,
        planner_agent=PlannerAgent(llm_service=LLMService(provider=planner_p)),
        test_adequacy_agent=TestAdequacyAgent(llm_service=LLMService(provider=test_p)),
    )

    assert result["status"] == "COMPLETED"
    findings = extract_candidate_findings(result)
    assert len(findings) == 1
    assert findings[0].issue_type == IssueType.TEST_ADEQUACY
