"""Unit tests for BaseSpecialistAgent, SpecialistContext, and candidate finding enrichment."""

import uuid

import pytest
from app.agents.base import (
    BaseSpecialistAgent,
    SpecialistContext,
    SpecialistReviewOutput,
    build_specialist_context,
)
from app.orchestration.errors import (
    InvalidSpecialistOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.orchestration.state import (
    ReviewState,
    create_initial_review_state,
    extract_candidate_findings,
    merge_candidate_findings,
    merge_error_messages,
    merge_specialist_errors,
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


class DummySpecialistAgent(BaseSpecialistAgent):
    """Concrete specialist agent test subclass."""

    def __init__(
        self,
        name: str = "dummy_agent",
        issue_type: IssueType = IssueType.BUG_LOGIC,
        llm_service: LLMService | None = None,
    ) -> None:
        super().__init__(
            name=name,
            issue_type=issue_type,
            system_prompt="You are a dummy test agent.",
            prompt_version="1.0.0",
            llm_service=llm_service,
        )

    def build_user_prompt(self, context: SpecialistContext) -> str:
        return f"Review files: {', '.join(context.changed_files)}"


@pytest.fixture
def sample_context() -> SpecialistContext:
    evidence = {
        "evidence_type": "STATIC_ANALYSIS",
        "file_path": "backend/app/auth.py",
        "start_line": 20,
        "end_line": 25,
        "snippet": "SECRET_KEY = 'hardcoded'",
        "corroborating_tool": "semgrep",
        "rule_or_cve_id": "hardcoded-secret",
    }
    return SpecialistContext(
        review_run_id="run-test-base-01",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
        base_sha="b" * 40,
        pr_number=10,
        pr_title="Refactor auth",
        pr_author="octocat",
        changed_files=["backend/app/auth.py"],
        formatted_diff="--- a/backend/app/auth.py\n+++ b/backend/app/auth.py\n@@ -20,3 +20,4 @@\n+SECRET_KEY = 'hardcoded'\n",
        evidence_items=[evidence],
        focus_areas=["security", "authentication"],
        target_files=["backend/app/auth.py"],
    )


@pytest.mark.asyncio
async def test_specialist_review_happy_path(sample_context: SpecialistContext) -> None:
    """Verify specialist produces grounded candidate findings with provenance."""
    mock_finding = ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=20,
        side=FindingSide.RIGHT,
        title="Hardcoded JWT Secret",
        explanation="Secret key exposed directly in code.",
        recommendation="Use environment variables.",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/auth.py",
                start_line=20,
                end_line=20,
                snippet="+SECRET_KEY = 'hardcoded'",
            )
        ],
        raw_confidence=0.9,
    )
    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[mock_finding])
    )
    agent = DummySpecialistAgent(
        name="security_agent",
        issue_type=IssueType.SECURITY,
        llm_service=LLMService(provider=provider),
    )

    findings = await agent.review(sample_context)

    assert len(findings) == 1
    finding = findings[0]
    # Provenance enforcement
    assert finding.agent_name == "security_agent"
    assert finding.verification_status == VerificationStatus.UNVERIFIED
    assert finding.confidence_score == 0.0  # Must remain unverified prior to Critic
    assert finding.raw_confidence == 0.9
    assert finding.issue_type == IssueType.SECURITY
    assert finding.line_number == 20
    # Corroborated with matching static analysis evidence from context
    assert len(finding.evidence) >= 1
    assert any(e.corroborating_tool == "semgrep" for e in finding.evidence)


@pytest.mark.asyncio
async def test_specialist_empty_findings(sample_context: SpecialistContext) -> None:
    """Verify specialist handles clean code changes with zero findings."""
    provider = MockLLMProvider(default_response=SpecialistReviewOutput(findings=[]))
    agent = DummySpecialistAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(sample_context)
    assert findings == []


@pytest.mark.asyncio
async def test_specialist_synthesizes_evidence_if_omitted(
    sample_context: SpecialistContext,
) -> None:
    """Verify finding without evidence receives synthesized diff hunk evidence."""
    mock_finding = ReviewFinding(
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.MEDIUM,
        affected_file="backend/app/auth.py",
        line_number=20,
        title="Potential None Dereference",
        explanation="Object may be None when accessed.",
        recommendation="Check for None before access.",
        evidence=[],  # Omitted evidence
    )
    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[mock_finding])
    )
    agent = DummySpecialistAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(sample_context)
    assert len(findings) == 1
    # Evidence was synthesized from diff coordinates
    assert len(findings[0].evidence) >= 1
    assert findings[0].evidence[0].start_line == 20
    assert findings[0].evidence[0].file_path == "backend/app/auth.py"


@pytest.mark.asyncio
async def test_specialist_malformed_output_raises_invalid_specialist_output(
    sample_context: SpecialistContext,
) -> None:
    """Verify malformed LLM response raises InvalidSpecialistOutputError with retryable=False."""
    provider = MockLLMProvider(default_response="not json at all")
    agent = DummySpecialistAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(InvalidSpecialistOutputError) as exc_info:
        await agent.review(sample_context)

    assert exc_info.value.retryable is False
    assert exc_info.value.category.value == "INVALID_SPECIALIST_OUTPUT"
    assert exc_info.value.details.get("agent_name") == "dummy_agent"


@pytest.mark.asyncio
async def test_specialist_timeout_propagates(sample_context: SpecialistContext) -> None:
    """Verify LLM timeout propagates as LLMTimeoutError with retryable=True."""
    provider = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Timed out", timeout_seconds=1.0)
    )
    agent = DummySpecialistAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(LLMTimeoutError) as exc_info:
        await agent.review(sample_context)

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_specialist_execute_node_isolates_failure() -> None:
    """Verify execute_node traps exception and returns structured specialist_errors."""
    state = create_initial_review_state(
        review_run_id="run-node-fail",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=5,
        commit_sha="a" * 40,
    )
    provider = MockLLMProvider(
        should_raise=LLMProviderError(
            message="503 Service Unavailable", status_code=503
        )
    )
    agent = DummySpecialistAgent(
        name="bug_logic_agent", llm_service=LLMService(provider=provider)
    )

    result = await agent.execute_node(state, raise_exceptions=False)

    assert result["candidate_findings"] == []
    assert len(result["specialist_errors"]) == 1
    err = result["specialist_errors"][0]
    assert err["agent_name"] == "bug_logic_agent"
    assert err["retryable"] is True
    assert err["error_category"] == "LLM_PROVIDER_ERROR"
    assert len(result["error_messages"]) == 1


@pytest.mark.asyncio
async def test_specialist_execute_node_re_raises_when_configured() -> None:
    """Verify execute_node re-raises when raise_exceptions=True."""
    state = create_initial_review_state(
        review_run_id="run-node-raise",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=5,
        commit_sha="a" * 40,
    )
    provider = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Timeout", timeout_seconds=2.0)
    )
    agent = DummySpecialistAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(LLMTimeoutError):
        await agent.execute_node(state, raise_exceptions=True)


def test_build_specialist_context_from_state() -> None:
    """Verify build_specialist_context correctly extracts and bounds state context."""
    plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent"],
        focus_areas=["Auth tokens"],
        target_files=["backend/app/auth.py"],
        is_large_pr=True,
        chunking_strategy="FILE_MODULE",
        file_chunks=[["backend/app/auth.py"]],
    )
    state = create_initial_review_state(
        review_run_id="run-builder-ctx",
        repository_id=1,
        repository_full_name="owner/repo",
        pr_number=12,
        commit_sha="c" * 40,
        base_sha="b" * 40,
        pr_title="PR Title",
        pr_author="author",
        changed_files=["backend/app/auth.py"],
    )
    state["review_plan"] = plan
    state["execution_metadata"]["prepared_context"] = {
        "formatted_diff": "+line of code",
        "diff_truncated": False,
        "changed_files": ["backend/app/auth.py"],
        "evidence_items": [],
        "is_large_pr": True,
        "chunking_strategy": "FILE_MODULE",
        "file_chunks": [["backend/app/auth.py"]],
    }

    ctx = build_specialist_context(state, "security_agent")

    assert ctx.review_run_id == "run-builder-ctx"
    assert ctx.commit_sha == "c" * 40
    assert ctx.base_sha == "b" * 40
    assert ctx.focus_areas == ["Auth tokens"]
    assert ctx.target_files == ["backend/app/auth.py"]
    assert ctx.is_large_pr is True
    assert ctx.chunking_strategy == "FILE_MODULE"
    assert ctx.formatted_diff == "+line of code"


def test_state_candidate_findings_reducer_and_helpers() -> None:
    """Verify merge_candidate_findings, merge_specialist_errors, and extract_candidate_findings."""
    finding_1 = {
        "finding_id": str(uuid.uuid4()),
        "issue_type": "SECURITY",
        "severity": "HIGH",
        "affected_file": "backend/app/auth.py",
        "line_number": 10,
        "title": "Secret leak",
        "explanation": "Leak in file.",
        "recommendation": "Fix leak.",
        "evidence": [],
    }
    finding_2 = {
        "finding_id": str(uuid.uuid4()),
        "issue_type": "BUG_LOGIC",
        "severity": "MEDIUM",
        "affected_file": "backend/app/logic.py",
        "line_number": 42,
        "title": "Off by one",
        "explanation": "Bound error.",
        "recommendation": "Fix bound.",
        "evidence": [],
    }

    # Reducer merge without duplicates
    merged = merge_candidate_findings([finding_1], [finding_2, finding_1])
    assert len(merged) == 2

    # Error reducer merge
    err_1 = {"agent_name": "agent_a", "error": "timeout"}
    err_2 = {"agent_name": "agent_b", "error": "500"}
    merged_errs = merge_specialist_errors([err_1], [err_2])
    assert len(merged_errs) == 2

    # Error messages reducer merge
    merged_msgs = merge_error_messages(["error 1"], ["error 2", "error 1"])
    assert len(merged_msgs) == 2

    # Helper extract_candidate_findings
    state: ReviewState = {
        "candidate_findings": [finding_1, finding_2],
    }
    findings = extract_candidate_findings(state)
    assert len(findings) == 2
    assert isinstance(findings[0], ReviewFinding)
    assert findings[0].affected_file == "backend/app/auth.py"
    assert findings[1].affected_file == "backend/app/logic.py"
