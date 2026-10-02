"""Unit tests for BugLogicAgent, bug logic prompts, and algorithmic correctness analysis."""

import pytest
from app.agents.base import SpecialistContext, SpecialistReviewOutput
from app.agents.bug_logic import BugLogicAgent
from app.agents.bug_logic_prompt import (
    BUG_LOGIC_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_bug_logic_user_prompt,
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
def bug_logic_context() -> SpecialistContext:
    return SpecialistContext(
        review_run_id="run-test-bug-01",
        repository_full_name="owner/repo",
        commit_sha="b" * 40,
        pr_number=202,
        pr_title="Fix pagination indexing",
        pr_author="dev",
        changed_files=["backend/app/pagination.py"],
        formatted_diff="--- a/backend/app/pagination.py\n+++ b/backend/app/pagination.py\n@@ -15,3 +15,3 @@\n-for i in range(len(items)):\n+for i in range(len(items) + 1):\n     process(items[i])\n",
        focus_areas=["Boundary conditions", "Index errors"],
        target_files=["backend/app/pagination.py"],
    )


@pytest.mark.asyncio
async def test_bug_logic_agent_detects_off_by_one(
    bug_logic_context: SpecialistContext,
) -> None:
    """Verify BugLogicAgent discovers off-by-one IndexError and grounds evidence."""
    finding_raw = ReviewFinding(
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.HIGH,
        affected_file="backend/app/pagination.py",
        line_number=16,
        side=FindingSide.RIGHT,
        title="Off-by-one IndexError in iteration bound",
        explanation="Loop range extends to len(items) + 1, causing IndexError on final iteration.",
        recommendation="Use `range(len(items))` or iterate directly over `items`.",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/pagination.py",
                start_line=15,
                end_line=16,
                snippet="+for i in range(len(items) + 1):\n     process(items[i])",
            )
        ],
        raw_confidence=0.92,
    )

    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[finding_raw])
    )
    agent = BugLogicAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(bug_logic_context)

    assert len(findings) == 1
    f = findings[0]
    assert f.agent_name == "bug_logic_agent"
    assert f.issue_type == IssueType.BUG_LOGIC
    assert f.severity == Severity.HIGH
    assert f.verification_status == VerificationStatus.UNVERIFIED
    assert f.confidence_score == 0.0
    assert f.line_number == 16
    assert len(f.evidence) == 1
    assert f.evidence[0].file_path == "backend/app/pagination.py"


@pytest.mark.asyncio
async def test_bug_logic_agent_multiple_findings(
    bug_logic_context: SpecialistContext,
) -> None:
    """Verify BugLogicAgent handles multiple candidate logic defects."""
    f1 = ReviewFinding(
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.HIGH,
        affected_file="backend/app/pagination.py",
        line_number=16,
        title="Off-by-one IndexError",
        explanation="Index out of range.",
        recommendation="Fix range.",
        evidence=[],
    )
    f2 = ReviewFinding(
        issue_type=IssueType.BUG_LOGIC,
        severity=Severity.MEDIUM,
        affected_file="backend/app/pagination.py",
        line_number=17,
        title="Unchecked None argument",
        explanation="process() fails when items[i] is None.",
        recommendation="Validate item before processing.",
        evidence=[],
    )
    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[f1, f2])
    )
    agent = BugLogicAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(bug_logic_context)
    assert len(findings) == 2
    assert findings[0].title == "Off-by-one IndexError"
    assert findings[1].title == "Unchecked None argument"
    assert all(f.agent_name == "bug_logic_agent" for f in findings)


@pytest.mark.asyncio
async def test_bug_logic_agent_empty_findings(
    bug_logic_context: SpecialistContext,
) -> None:
    """Verify clean PR produces empty candidate findings."""
    provider = MockLLMProvider(default_response=SpecialistReviewOutput(findings=[]))
    agent = BugLogicAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(bug_logic_context)
    assert findings == []


@pytest.mark.asyncio
async def test_bug_logic_agent_malformed_output(
    bug_logic_context: SpecialistContext,
) -> None:
    """Verify malformed JSON raises InvalidSpecialistOutputError."""
    provider = MockLLMProvider(default_response="invalid string not JSON")
    agent = BugLogicAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(InvalidSpecialistOutputError):
        await agent.review(bug_logic_context)


def test_bug_logic_prompt_formatting(bug_logic_context: SpecialistContext) -> None:
    """Verify prompt builder formats diff, focus areas, and instructions."""
    prompt = build_bug_logic_user_prompt(bug_logic_context)

    assert "Fix pagination indexing" in prompt
    assert "Boundary conditions" in prompt
    assert "backend/app/pagination.py" in prompt
    assert "+for i in range(len(items) + 1):" in prompt
    assert "SpecialistReviewOutput" in prompt


def test_bug_logic_system_prompt_rules() -> None:
    """Verify system prompt enforces distinction between observed evidence and inference."""
    assert "DISTINGUISH EVIDENCE VS INFERENCE" in BUG_LOGIC_SYSTEM_PROMPT
    assert "Do NOT fabricate runtime behavior" in BUG_LOGIC_SYSTEM_PROMPT
    assert "CANDIDATE FINDINGS ONLY" in BUG_LOGIC_SYSTEM_PROMPT
    assert PROMPT_VERSION == "1.0.0"
