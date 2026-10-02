"""Unit tests for ErrorHandlingAgent, error handling prompts, and resilience analysis."""

import pytest
from app.agents.base import SpecialistContext, SpecialistReviewOutput
from app.agents.error_handling import ErrorHandlingAgent
from app.agents.error_handling_prompt import (
    ERROR_HANDLING_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_error_handling_user_prompt,
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
def error_handling_context() -> SpecialistContext:
    return SpecialistContext(
        review_run_id="run-test-err-01",
        repository_full_name="owner/repo",
        commit_sha="c" * 40,
        pr_number=303,
        pr_title="Add database sync routine",
        pr_author="dev",
        changed_files=["backend/app/sync.py"],
        formatted_diff="--- a/backend/app/sync.py\n+++ b/backend/app/sync.py\n@@ -50,6 +50,7 @@\n+try:\n+    client.sync_records()\n+except Exception:\n+    pass\n",
        focus_areas=["Exception handling", "Database resilience"],
        target_files=["backend/app/sync.py"],
    )


@pytest.mark.asyncio
async def test_error_handling_agent_detects_swallowed_exception(
    error_handling_context: SpecialistContext,
) -> None:
    """Verify ErrorHandlingAgent detects swallowed exception and flags blast radius."""
    finding_raw = ReviewFinding(
        issue_type=IssueType.ERROR_HANDLING,
        severity=Severity.HIGH,
        affected_file="backend/app/sync.py",
        line_number=53,
        side=FindingSide.RIGHT,
        title="Swallowed Exception (`except Exception: pass`)",
        explanation="Blanket exception catch silently suppresses all sync failures, causing undetectable data desynchronization.",
        recommendation="Log the exception with traceback and raise a typed SyncFailureError or trigger dead-letter queue.",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/sync.py",
                start_line=50,
                end_line=53,
                snippet="+except Exception:\n+    pass",
            )
        ],
        raw_confidence=0.96,
    )

    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[finding_raw])
    )
    agent = ErrorHandlingAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(error_handling_context)

    assert len(findings) == 1
    f = findings[0]
    assert f.agent_name == "error_handling_agent"
    assert f.issue_type == IssueType.ERROR_HANDLING
    assert f.severity == Severity.HIGH
    assert f.verification_status == VerificationStatus.UNVERIFIED
    assert f.confidence_score == 0.0
    assert f.line_number == 53
    assert len(f.evidence) == 1
    assert "except Exception:\n+    pass" in f.evidence[0].snippet


@pytest.mark.asyncio
async def test_error_handling_agent_multiple_findings(
    error_handling_context: SpecialistContext,
) -> None:
    """Verify ErrorHandlingAgent handles multiple candidate error handling defects."""
    f1 = ReviewFinding(
        issue_type=IssueType.ERROR_HANDLING,
        severity=Severity.HIGH,
        affected_file="backend/app/sync.py",
        line_number=53,
        title="Swallowed Exception",
        explanation="Silent failure.",
        recommendation="Log and raise.",
        evidence=[],
    )
    f2 = ReviewFinding(
        issue_type=IssueType.ERROR_HANDLING,
        severity=Severity.MEDIUM,
        affected_file="backend/app/sync.py",
        line_number=60,
        title="Missing Connection Cleanup",
        explanation="Connection not closed in finally block.",
        recommendation="Use context manager.",
        evidence=[],
    )
    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[f1, f2])
    )
    agent = ErrorHandlingAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(error_handling_context)
    assert len(findings) == 2
    assert findings[0].title == "Swallowed Exception"
    assert findings[1].title == "Missing Connection Cleanup"
    assert all(f.agent_name == "error_handling_agent" for f in findings)


@pytest.mark.asyncio
async def test_error_handling_agent_empty_findings(
    error_handling_context: SpecialistContext,
) -> None:
    """Verify clean PR produces empty candidate findings."""
    provider = MockLLMProvider(default_response=SpecialistReviewOutput(findings=[]))
    agent = ErrorHandlingAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(error_handling_context)
    assert findings == []


@pytest.mark.asyncio
async def test_error_handling_agent_malformed_output(
    error_handling_context: SpecialistContext,
) -> None:
    """Verify malformed JSON raises InvalidSpecialistOutputError."""
    provider = MockLLMProvider(default_response="malformed output")
    agent = ErrorHandlingAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(InvalidSpecialistOutputError):
        await agent.review(error_handling_context)


def test_error_handling_prompt_formatting(
    error_handling_context: SpecialistContext,
) -> None:
    """Verify prompt builder formats diff, focus areas, and instructions."""
    prompt = build_error_handling_user_prompt(error_handling_context)

    assert "Add database sync routine" in prompt
    assert "Exception handling" in prompt
    assert "backend/app/sync.py" in prompt
    assert "+    client.sync_records()" in prompt
    assert "SpecialistReviewOutput" in prompt


def test_error_handling_system_prompt_rules() -> None:
    """Verify system prompt enforces failure blast radius and resilience rules."""
    assert "FAILURE BLAST RADIUS ANALYSIS" in ERROR_HANDLING_SYSTEM_PROMPT
    assert "EXAMINE BOTH NEW AND MODIFIED ERROR PATHS" in ERROR_HANDLING_SYSTEM_PROMPT
    assert "CANDIDATE FINDINGS ONLY" in ERROR_HANDLING_SYSTEM_PROMPT
    assert PROMPT_VERSION == "1.0.0"
