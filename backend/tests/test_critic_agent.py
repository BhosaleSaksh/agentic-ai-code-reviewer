"""Unit tests for CriticAgent, prompt rendering, verification decisions, and error handling."""

import pytest
from app.agents.critic import CriticAgent
from app.agents.critic_prompt import (
    CRITIC_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_critic_user_prompt,
)
from app.orchestration.errors import (
    InvalidCriticOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    EvidenceType,
    FileChangeType,
    FindingSide,
    IssueType,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.verification import (
    CriticStructuredOutput,
    VerificationContext,
)
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService


@pytest.fixture
def sample_finding() -> ReviewFinding:
    """Fixture returning a candidate ReviewFinding."""
    return ReviewFinding(
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        affected_file="backend/app/auth.py",
        line_number=15,
        side=FindingSide.RIGHT,
        title="Command Injection in subprocess call",
        explanation="Untrusted user input is passed directly to shell=True.",
        recommendation="Pass command arguments as a list without shell=True.",
        evidence=[
            EvidenceModel(
                evidence_type=EvidenceType.DIFF_HUNK,
                file_path="backend/app/auth.py",
                start_line=15,
                end_line=15,
                snippet="+    subprocess.run(f'echo {cmd}', shell=True)",
            )
        ],
        raw_confidence=0.85,
        agent_name="security_agent",
        verification_status=VerificationStatus.UNVERIFIED,
    )


@pytest.fixture
def sample_diff() -> ParsedDiff:
    """Fixture returning a ParsedDiff covering line 15."""
    hunk = DiffHunk(
        old_start=10,
        old_count=3,
        new_start=10,
        new_count=7,
        header="@@ -10,3 +10,7 @@",
        lines=[
            DiffLine(
                line_type=DiffLineType.ADDED,
                new_line_number=15,
                content="    subprocess.run(f'echo {cmd}', shell=True)",
                raw_line="+    subprocess.run(f'echo {cmd}', shell=True)",
            )
        ],
    )
    diff_file = DiffFile(
        old_path="backend/app/auth.py",
        new_path="backend/app/auth.py",
        status=FileChangeType.MODIFIED,
        hunks=[hunk],
    )
    return ParsedDiff(files=[diff_file])


def test_critic_prompt_rendering(sample_finding: ReviewFinding) -> None:
    """Verify build_critic_user_prompt formats candidate finding, diff excerpt, and static signals."""
    context = VerificationContext(
        review_run_id="run-prompt-01",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
        candidate_finding=sample_finding,
        file_exists=True,
        line_in_diff=True,
        line_in_changed_hunk=True,
        diff_snippet="+    subprocess.run(f'echo {cmd}', shell=True)",
        hunk_header="@@ -10,3 +10,7 @@",
        agent_provenance="security_agent",
        raw_confidence=0.85,
    )

    prompt = build_critic_user_prompt(context)

    assert f"v{PROMPT_VERSION}" in prompt
    assert "owner/repo" in prompt
    assert sample_finding.title in prompt
    assert "security_agent" in prompt
    assert "subprocess.run" in prompt
    assert "VERIFICATION TASK" in prompt
    assert CRITIC_SYSTEM_PROMPT is not None


@pytest.mark.asyncio
async def test_critic_verify_candidate_verified_decision(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify CriticAgent produces a VERIFIED result when evidence is sufficient."""
    mock_critic_output = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.90,
        evidence_sufficiency=True,
        contradiction_detected=False,
        critic_notes="Direct shell injection vulnerability introduced in diff.",
        verification_reasons=[
            "Direct string interpolation in shell=True subprocess call."
        ],
    )

    provider = MockLLMProvider(default_response=mock_critic_output)
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    result = await critic.verify_candidate(
        finding=sample_finding,
        parsed_diff=sample_diff,
        changed_files=["backend/app/auth.py"],
        review_run_id="run-test-01",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
    )

    assert result.is_verified is True
    assert result.verification_status == VerificationStatus.VERIFIED
    assert result.confidence_score >= 0.90
    assert result.verifier_notes is not None
    assert "Direct shell injection" in result.verifier_notes

    # Finding was updated in-place
    assert sample_finding.verification_status == VerificationStatus.VERIFIED
    assert sample_finding.confidence_score == result.confidence_score


@pytest.mark.asyncio
async def test_critic_verify_candidate_rejected_decision(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify CriticAgent produces a REJECTED result when LLM detects contradiction or low confidence."""
    mock_critic_output = CriticStructuredOutput(
        decision="REJECTED",
        calibrated_confidence=0.35,
        evidence_sufficiency=False,
        contradiction_detected=True,
        critic_notes="Input variable 'cmd' is an internal constant enum, not user input.",
        rejection_reasons=["Variable is not externally controllable."],
    )

    provider = MockLLMProvider(default_response=mock_critic_output)
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    result = await critic.verify_candidate(
        finding=sample_finding,
        parsed_diff=sample_diff,
        changed_files=["backend/app/auth.py"],
        review_run_id="run-test-02",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
    )

    assert result.is_rejected is True
    assert result.verification_status == VerificationStatus.REJECTED
    assert result.confidence_score <= 0.40
    assert "Variable is not externally controllable" in "; ".join(
        result.rejected_reasons
    )

    # Finding was updated in-place with rejection status
    assert sample_finding.verification_status == VerificationStatus.REJECTED
    assert sample_finding.is_rejected is True


@pytest.mark.asyncio
async def test_critic_deterministic_rejection_bypasses_llm(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify that deterministically rejected findings never invoke the Critic LLM."""
    # Finding points to non-existent file
    sample_finding.affected_file = "non_existent.py"

    provider = MockLLMProvider()  # Unconfigured provider will count calls
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    result = await critic.verify_candidate(
        finding=sample_finding,
        parsed_diff=sample_diff,
        changed_files=["backend/app/auth.py"],
        review_run_id="run-test-03",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
    )

    # Deterministically rejected
    assert result.is_rejected is True
    assert result.deterministic_validation_passed is False
    assert result.calibrated_by == "deterministic_validator"
    # LLM was NEVER called
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_critic_specialist_confidence_not_blindly_copied(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify that Critic independently calibrates confidence rather than copying specialist confidence."""
    # Specialist provided very high confidence (0.95)
    sample_finding.raw_confidence = 0.95

    # Critic independently evaluates lower confidence due to missing context
    mock_critic_output = CriticStructuredOutput(
        decision="REJECTED",
        calibrated_confidence=0.55,
        evidence_sufficiency=False,
        critic_notes="Insufficient evidence to substantiate vulnerability.",
    )

    provider = MockLLMProvider(default_response=mock_critic_output)
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    result = await critic.verify_candidate(
        finding=sample_finding,
        parsed_diff=sample_diff,
        changed_files=["backend/app/auth.py"],
        review_run_id="run-test-04",
        repository_full_name="owner/repo",
        commit_sha="a" * 40,
    )

    # Confidence was NOT copied from specialist's 0.95
    assert result.confidence_score < 0.60
    assert result.confidence_score != sample_finding.raw_confidence


@pytest.mark.asyncio
async def test_critic_retryable_timeout_propagates(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify LLM timeout error propagates with retryable=True."""
    provider = MockLLMProvider(
        should_raise=LLMTimeoutError(message="Critic timeout", timeout_seconds=2.0)
    )
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(LLMTimeoutError) as exc_info:
        await critic.verify_candidate(
            finding=sample_finding,
            parsed_diff=sample_diff,
            changed_files=["backend/app/auth.py"],
            review_run_id="run-test-05",
            repository_full_name="owner/repo",
            commit_sha="a" * 40,
        )

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_critic_transient_provider_error_propagates(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify 503 LLMProviderError propagates with retryable=True."""
    provider = MockLLMProvider(
        should_raise=LLMProviderError(
            message="503 Service Unavailable", status_code=503
        )
    )
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(LLMProviderError) as exc_info:
        await critic.verify_candidate(
            finding=sample_finding,
            parsed_diff=sample_diff,
            changed_files=["backend/app/auth.py"],
            review_run_id="run-test-06",
            repository_full_name="owner/repo",
            commit_sha="a" * 40,
        )

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_critic_malformed_output_raises_invalid_critic_output(
    sample_finding: ReviewFinding, sample_diff: ParsedDiff
) -> None:
    """Verify non-retryable InvalidCriticOutputError raised on unparseable output."""
    provider = MockLLMProvider(default_response="MALFORMED_NON_JSON")
    critic = CriticAgent(llm_service=LLMService(provider=provider))

    with pytest.raises(InvalidCriticOutputError) as exc_info:
        await critic.verify_candidate(
            finding=sample_finding,
            parsed_diff=sample_diff,
            changed_files=["backend/app/auth.py"],
            review_run_id="run-test-07",
            repository_full_name="owner/repo",
            commit_sha="a" * 40,
        )

    assert exc_info.value.retryable is False
