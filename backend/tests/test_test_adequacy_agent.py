"""Unit tests for TestAdequacyAgent, test adequacy prompts, and coverage gap analysis."""

import pytest
from app.agents.base import SpecialistContext, SpecialistReviewOutput
from app.agents.test_adequacy import TestAdequacyAgent
from app.agents.test_adequacy_prompt import (
    PROMPT_VERSION,
    TEST_ADEQUACY_SYSTEM_PROMPT,
    build_test_adequacy_user_prompt,
)
from app.orchestration.errors import InvalidSpecialistOutputError
from app.schemas.enums import (
    EvidenceType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService


@pytest.fixture
def test_adequacy_context_no_tests() -> SpecialistContext:
    return SpecialistContext(
        review_run_id="run-test-adequacy-01",
        repository_full_name="owner/repo",
        commit_sha="d" * 40,
        pr_number=404,
        pr_title="Introduce refund calculation algorithm",
        pr_author="dev",
        changed_files=["backend/app/billing/refund.py"],
        formatted_diff="--- a/backend/app/billing/refund.py\n+++ b/backend/app/billing/refund.py\n@@ -10,6 +10,12 @@\n+def calculate_tier_refund(tier: str, amount: float) -> float:\n+    if tier == 'VIP':\n+        return amount * 0.9\n+    if tier == 'PARTNER':\n+        return amount * 0.8\n+    return amount * 0.5\n",
        focus_areas=["Billing logic", "Test coverage"],
        target_files=["backend/app/billing/refund.py"],
    )


@pytest.fixture
def test_adequacy_context_with_tests() -> SpecialistContext:
    return SpecialistContext(
        review_run_id="run-test-adequacy-02",
        repository_full_name="owner/repo",
        commit_sha="e" * 40,
        pr_number=405,
        pr_title="Add refund calculation and tests",
        pr_author="dev",
        changed_files=[
            "backend/app/billing/refund.py",
            "backend/tests/test_refund.py",
        ],
        formatted_diff="--- a/backend/app/billing/refund.py\n+++ b/backend/app/billing/refund.py\n@@ -10,2 +10,4 @@\n+def refund(): pass\n--- a/backend/tests/test_refund.py\n+++ b/backend/tests/test_refund.py\n@@ -1,2 +1,3 @@\n+def test_refund(): assert True\n",
        focus_areas=["Test assertions"],
        target_files=["backend/app/billing/refund.py", "backend/tests/test_refund.py"],
    )


@pytest.mark.asyncio
async def test_test_adequacy_agent_detects_untested_branches(
    test_adequacy_context_no_tests: SpecialistContext,
) -> None:
    """Verify TestAdequacyAgent discovers untested conditional branches in production code."""
    finding_raw = ReviewFinding(
        issue_type=IssueType.TEST_ADEQUACY,
        severity=Severity.HIGH,
        affected_file="backend/app/billing/refund.py",
        line_number=11,
        side=FindingSide.RIGHT,
        title="Untested branching logic for VIP and PARTNER refund tiers",
        explanation="New calculate_tier_refund function introduces multiple decision branches without accompanying unit tests.",
        recommendation="Add unit tests covering VIP, PARTNER, and default tier branches with edge-case amounts (0, negative, float).",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/billing/refund.py",
                start_line=10,
                end_line=15,
                snippet="+if tier == 'VIP':\n+    return amount * 0.9",
            )
        ],
        raw_confidence=0.91,
    )

    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[finding_raw])
    )
    agent = TestAdequacyAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(test_adequacy_context_no_tests)

    assert len(findings) == 1
    f = findings[0]
    assert f.agent_name == "test_adequacy_agent"
    assert f.issue_type == IssueType.TEST_ADEQUACY
    assert f.severity == Severity.HIGH
    assert f.verification_status == VerificationStatus.UNVERIFIED
    assert f.confidence_score == 0.0
    assert f.line_number == 11
    assert "VIP and PARTNER" in f.title
    assert len(f.evidence) == 1


@pytest.mark.asyncio
async def test_test_adequacy_agent_detects_tautological_assertion(
    test_adequacy_context_with_tests: SpecialistContext,
) -> None:
    """Verify TestAdequacyAgent detects tautological test assertions like `assert True`."""
    finding_raw = ReviewFinding(
        issue_type=IssueType.TEST_ADEQUACY,
        severity=Severity.MEDIUM,
        affected_file="backend/tests/test_refund.py",
        line_number=2,
        title="Tautological test assertion (`assert True`)",
        explanation="The test does not assert the return value of calculate_tier_refund.",
        recommendation="Replace `assert True` with explicit assertions verifying refund amount calculation.",
        evidence=[],
    )
    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[finding_raw])
    )
    agent = TestAdequacyAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(test_adequacy_context_with_tests)
    assert len(findings) == 1
    assert findings[0].affected_file == "backend/tests/test_refund.py"
    assert findings[0].agent_name == "test_adequacy_agent"


@pytest.mark.asyncio
async def test_test_adequacy_agent_empty_findings(
    test_adequacy_context_with_tests: SpecialistContext,
) -> None:
    """Verify clean PR with adequate tests produces zero findings."""
    provider = MockLLMProvider(default_response=SpecialistReviewOutput(findings=[]))
    agent = TestAdequacyAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(test_adequacy_context_with_tests)
    assert findings == []


@pytest.mark.asyncio
async def test_test_adequacy_agent_malformed_output(
    test_adequacy_context_no_tests: SpecialistContext,
) -> None:
    """Verify malformed JSON raises InvalidSpecialistOutputError."""
    provider = MockLLMProvider(default_response="not json")
    agent = TestAdequacyAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(InvalidSpecialistOutputError):
        await agent.review(test_adequacy_context_no_tests)


def test_test_adequacy_prompt_inventory_without_tests(
    test_adequacy_context_no_tests: SpecialistContext,
) -> None:
    """Verify prompt notes the absence of test files in the PR."""
    prompt = build_test_adequacy_user_prompt(test_adequacy_context_no_tests)

    assert "Production Files (1)" in prompt
    assert "backend/app/billing/refund.py" in prompt
    assert "No test files were modified or added" in prompt
    assert "SpecialistReviewOutput" in prompt


def test_test_adequacy_prompt_inventory_with_tests(
    test_adequacy_context_with_tests: SpecialistContext,
) -> None:
    """Verify prompt includes both production and test files in inventory."""
    prompt = build_test_adequacy_user_prompt(test_adequacy_context_with_tests)

    assert "Production Files (1)" in prompt
    assert "Test Files (1)" in prompt
    assert "backend/tests/test_refund.py" in prompt


def test_test_adequacy_system_prompt_rules() -> None:
    """Verify system prompt enforces reasoning from actual behavior and representation limitations."""
    assert "REASON FROM ACTUAL CHANGED BEHAVIOR" in TEST_ADEQUACY_SYSTEM_PROMPT
    assert "REPRESENT CONTEXT LIMITATIONS EXPLICITLY" in TEST_ADEQUACY_SYSTEM_PROMPT
    assert "CANDIDATE FINDINGS ONLY" in TEST_ADEQUACY_SYSTEM_PROMPT
    assert PROMPT_VERSION == "1.0.0"
