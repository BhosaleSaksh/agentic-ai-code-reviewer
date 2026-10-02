"""Unit tests for SecurityAgent, security prompts, and static tool evidence integration."""

import pytest
from app.agents.base import SpecialistContext, SpecialistReviewOutput
from app.agents.security import SecurityAgent
from app.agents.security_prompt import (
    PROMPT_VERSION,
    SECURITY_SYSTEM_PROMPT,
    build_security_user_prompt,
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
def security_context() -> SpecialistContext:
    evidence = {
        "evidence_type": "STATIC_ANALYSIS",
        "file_path": "backend/app/auth.py",
        "start_line": 35,
        "end_line": 38,
        "snippet": "query = f'SELECT * FROM users WHERE user = \"{username}\"'",
        "corroborating_tool": "bandit",
        "rule_or_cve_id": "bandit.B608",
    }
    return SpecialistContext(
        review_run_id="run-test-sec-01",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
        pr_number=101,
        pr_title="Add user query endpoint",
        pr_author="dev",
        changed_files=["backend/app/auth.py"],
        formatted_diff="--- a/backend/app/auth.py\n+++ b/backend/app/auth.py\n@@ -35,4 +35,5 @@\n+query = f'SELECT * FROM users WHERE user = \"{username}\"'\n",
        evidence_items=[evidence],
        focus_areas=["SQL Injection", "Input Sanitization"],
        target_files=["backend/app/auth.py"],
    )


@pytest.mark.asyncio
async def test_security_agent_detects_sqli_with_bandit_corroboration(
    security_context: SpecialistContext,
) -> None:
    """Verify SecurityAgent incorporates static analysis tool evidence into candidate finding."""
    candidate_raw = ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.CRITICAL,
        affected_file="backend/app/auth.py",
        line_number=35,
        side=FindingSide.RIGHT,
        title="SQL Injection via string formatting",
        explanation="Untrusted username parameter interpolated directly into SQL query (CWE-89).",
        recommendation="Use parameterized queries with SQLAlchemy text bindparams.",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/auth.py",
                start_line=35,
                end_line=35,
                snippet="+query = f'SELECT * FROM users WHERE user = \"{username}\"'",
            )
        ],
        raw_confidence=0.95,
    )

    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[candidate_raw])
    )
    agent = SecurityAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(security_context)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.agent_name == "security_agent"
    assert finding.verification_status == VerificationStatus.UNVERIFIED
    assert finding.confidence_score == 0.0
    assert finding.issue_type == IssueType.SECURITY
    assert finding.severity == Severity.CRITICAL
    assert finding.raw_confidence == 0.95

    # Check that the Bandit evidence from context was automatically corroborated
    assert any(
        e.rule_or_cve_id == "bandit.B608" and e.corroborating_tool == "bandit"
        for e in finding.evidence
    )


@pytest.mark.asyncio
async def test_security_agent_multiple_findings(
    security_context: SpecialistContext,
) -> None:
    """Verify SecurityAgent handles multiple security candidate findings."""
    f1 = ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.CRITICAL,
        affected_file="backend/app/auth.py",
        line_number=35,
        title="SQL Injection",
        explanation="CWE-89 SQL Injection",
        recommendation="Parametrize query.",
        evidence=[],
    )
    f2 = ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=45,
        title="Hardcoded API secret",
        explanation="CWE-798 Hardcoded credential",
        recommendation="Use environment variables.",
        evidence=[],
    )
    provider = MockLLMProvider(
        default_response=SpecialistReviewOutput(findings=[f1, f2])
    )
    agent = SecurityAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(security_context)
    assert len(findings) == 2
    assert findings[0].title == "SQL Injection"
    assert findings[1].title == "Hardcoded API secret"
    assert all(f.agent_name == "security_agent" for f in findings)
    assert all(f.verification_status == VerificationStatus.UNVERIFIED for f in findings)


@pytest.mark.asyncio
async def test_security_agent_empty_findings(
    security_context: SpecialistContext,
) -> None:
    """Verify clean review produces empty candidate findings."""
    provider = MockLLMProvider(default_response=SpecialistReviewOutput(findings=[]))
    agent = SecurityAgent(llm_service=LLMService(provider=provider))

    findings = await agent.review(security_context)
    assert findings == []


@pytest.mark.asyncio
async def test_security_agent_malformed_output_error(
    security_context: SpecialistContext,
) -> None:
    """Verify malformed JSON raises InvalidSpecialistOutputError."""
    provider = MockLLMProvider(default_response="{not: valid json}")
    agent = SecurityAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(InvalidSpecialistOutputError) as exc_info:
        await agent.review(security_context)

    assert exc_info.value.category.value == "INVALID_SPECIALIST_OUTPUT"
    assert exc_info.value.retryable is False


def test_security_prompt_formatting(security_context: SpecialistContext) -> None:
    """Verify prompt builder includes PR metadata, static analysis items, and unified diff."""
    prompt = build_security_user_prompt(security_context)

    assert "owner/repo" in prompt
    assert security_context.commit_sha in prompt
    assert "SQL Injection" in prompt
    assert "bandit.B608" in prompt
    assert "SELECT * FROM users" in prompt
    assert "MODIFIED CODE DIFF" in prompt
    assert "SpecialistReviewOutput" in prompt


def test_security_system_prompt_rules() -> None:
    """Verify system prompt enforces candidate-only status and OWASP/CWE references."""
    assert "CANDIDATE FINDINGS ONLY" in SECURITY_SYSTEM_PROMPT
    assert (
        "Do NOT declare that an issue is a verified vulnerability"
        in SECURITY_SYSTEM_PROMPT
    )
    assert "EVIDENCE-FIRST GROUNDING" in SECURITY_SYSTEM_PROMPT
    assert PROMPT_VERSION == "1.0.0"
