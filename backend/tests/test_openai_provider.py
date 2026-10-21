"""Unit tests for OpenAILLMProvider, credential isolation, and error mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from app.agents.base import SpecialistReviewOutput
from app.core.config import Settings
from app.orchestration.errors import (
    LLMProviderError,
    LLMTimeoutError,
    WorkflowConfigurationError,
)
from app.schemas.enums import IssueType, Severity
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan
from app.schemas.verification import CriticStructuredOutput
from app.services.llm.base import LLMRequest
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.openai_provider import (
    OpenAILLMProvider,
    calculate_openai_cost,
    sanitize_error_message,
)
from app.services.llm.service import LLMService
from pydantic import SecretStr


def _create_mock_client() -> MagicMock:
    """Create a mock AsyncOpenAI client with chat.completions endpoints."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock()
    mock_client.chat.completions.parse = AsyncMock()
    return mock_client


@pytest.fixture
def mock_client() -> MagicMock:
    return _create_mock_client()


@pytest.fixture
def openai_provider(mock_client: MagicMock) -> OpenAILLMProvider:
    settings = Settings(
        LLM_PROVIDER="openai",
        OPENAI_API_KEY=SecretStr("sk-test-mock-dummy-key-for-unit-testing-only-12345"),
        OPENAI_MODEL="gpt-4o",
        LLM_MAX_RETRIES=2,
    )
    return OpenAILLMProvider(settings=settings, client=mock_client)


@pytest.mark.asyncio
async def test_openai_provider_generate_success(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify standard text generation extracts content, usage, and computes cost."""
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "LGTM. Code clean."
    mock_completion.choices = [mock_choice]
    mock_completion.usage.prompt_tokens = 1000
    mock_completion.usage.completion_tokens = 500
    mock_completion.usage.total_tokens = 1500

    mock_client.chat.completions.create.return_value = mock_completion

    req = LLMRequest(
        prompt="Review this code", system_prompt="You are a reviewer", model="gpt-4o"
    )
    resp = await openai_provider.generate(req)

    assert resp.content == "LGTM. Code clean."
    assert resp.prompt_tokens == 1000
    assert resp.completion_tokens == 500
    assert resp.total_tokens == 1500
    assert resp.model_name == "gpt-4o"
    assert resp.latency_seconds >= 0.0
    # gpt-4o cost: (1000/1M * 2.50) + (500/1M * 10.00) = 0.0025 + 0.0050 = 0.0075
    assert resp.estimated_cost_usd == pytest.approx(0.0075, rel=1e-3)


@pytest.mark.asyncio
async def test_openai_provider_generate_structured_planner(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify structured parsing of ReviewPlan contract."""
    expected_plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
        focus_areas=["Auth", "SQL"],
        target_files=["app/main.py"],
    )

    mock_parsed_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.parsed = expected_plan
    mock_choice.message.content = expected_plan.model_dump_json()
    mock_parsed_completion.choices = [mock_choice]
    mock_parsed_completion.usage.prompt_tokens = 200
    mock_parsed_completion.usage.completion_tokens = 100
    mock_parsed_completion.usage.total_tokens = 300

    mock_client.chat.completions.parse.return_value = mock_parsed_completion

    req = LLMRequest(prompt="Plan review for PR")
    plan, resp = await openai_provider.generate_structured(req, ReviewPlan)

    assert plan.review_scope == "FULL"
    assert "security_agent" in plan.active_agents
    assert resp.structured_output == expected_plan
    assert resp.total_tokens == 300


@pytest.mark.asyncio
async def test_openai_provider_generate_structured_specialist(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify structured parsing of SpecialistReviewOutput contract."""
    finding = ReviewFinding(
        affected_file="backend/app/auth.py",
        line_number=42,
        issue_type=IssueType.SECURITY,
        severity=Severity.HIGH,
        title="SQL injection risk",
        explanation="Raw string formatting in SQL query allows arbitrary SQL execution.",
        recommendation="Use parameterized query with SQLAlchemy text() bind parameters.",
    )
    expected_output = SpecialistReviewOutput(
        findings=[finding], summary="Found 1 critical issue"
    )

    mock_parsed_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.parsed = expected_output
    mock_choice.message.content = expected_output.model_dump_json()
    mock_parsed_completion.choices = [mock_choice]
    mock_parsed_completion.usage.prompt_tokens = 500
    mock_parsed_completion.usage.completion_tokens = 150
    mock_parsed_completion.usage.total_tokens = 650

    mock_client.chat.completions.parse.return_value = mock_parsed_completion

    req = LLMRequest(prompt="Review security of PR")
    out, resp = await openai_provider.generate_structured(req, SpecialistReviewOutput)

    assert len(out.findings) == 1
    assert out.findings[0].affected_file == "backend/app/auth.py"
    assert out.findings[0].line_number == 42
    assert resp.total_tokens == 650


@pytest.mark.asyncio
async def test_openai_provider_generate_structured_critic(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify structured parsing of CriticStructuredOutput contract."""
    critic_output = CriticStructuredOutput(
        decision="VERIFIED",
        calibrated_confidence=0.92,
        contradiction_detected=False,
        evidence_sufficiency=True,
        reasoning="Diff confirms raw sql string formatting is present on line 42",
    )

    mock_parsed_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.parsed = critic_output
    mock_choice.message.content = critic_output.model_dump_json()
    mock_parsed_completion.choices = [mock_choice]
    mock_parsed_completion.usage.prompt_tokens = 300
    mock_parsed_completion.usage.completion_tokens = 80
    mock_parsed_completion.usage.total_tokens = 380

    mock_client.chat.completions.parse.return_value = mock_parsed_completion

    req = LLMRequest(prompt="Verify candidate finding")
    verified, resp = await openai_provider.generate_structured(
        req, CriticStructuredOutput
    )

    assert verified.decision == "VERIFIED"
    assert verified.calibrated_confidence == 0.92
    assert resp.total_tokens == 380


@pytest.mark.asyncio
async def test_openai_provider_refusal_raises_non_retryable_error(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify model refusal raises non-retryable LLMProviderError."""
    mock_parsed_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = "I cannot review this code per content policy"
    mock_parsed_completion.choices = [mock_choice]

    mock_client.chat.completions.parse.return_value = mock_parsed_completion

    req = LLMRequest(prompt="Review restricted code")
    with pytest.raises(LLMProviderError) as exc_info:
        await openai_provider.generate_structured(req, ReviewPlan)

    assert exc_info.value.retryable is False
    assert exc_info.value.details.get("status_code") == 422
    assert "refused" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_openai_provider_rate_limit_mapped_to_retryable(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify RateLimitError maps to retryable LLMProviderError with 429 status."""
    dummy_req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    dummy_resp = httpx.Response(429, request=dummy_req)
    rate_limit_exc = openai.RateLimitError(
        message="Rate limit exceeded",
        response=dummy_resp,  # type: ignore[arg-type]
        body={"error": "Rate limit"},
    )
    mock_client.chat.completions.create.side_effect = rate_limit_exc

    req = LLMRequest(prompt="Test prompt")
    with pytest.raises(LLMProviderError) as exc_info:
        await openai_provider.generate(req)

    assert exc_info.value.retryable is True
    assert exc_info.value.details.get("status_code") == 429


@pytest.mark.asyncio
async def test_openai_provider_auth_error_mapped_to_non_retryable(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify AuthenticationError maps to non-retryable LLMProviderError with 401 status."""
    dummy_req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    dummy_resp = httpx.Response(401, request=dummy_req)
    auth_exc = openai.AuthenticationError(
        message="Invalid API Key provided",
        response=dummy_resp,  # type: ignore[arg-type]
        body={"error": "Invalid API Key"},
    )
    mock_client.chat.completions.create.side_effect = auth_exc

    req = LLMRequest(prompt="Test prompt")
    with pytest.raises(LLMProviderError) as exc_info:
        await openai_provider.generate(req)

    assert exc_info.value.retryable is False
    assert exc_info.value.details.get("status_code") == 401


@pytest.mark.asyncio
async def test_openai_provider_timeout_mapped_to_llm_timeout(
    openai_provider: OpenAILLMProvider, mock_client: MagicMock
) -> None:
    """Verify APITimeoutError maps to retryable LLMTimeoutError."""
    dummy_req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    timeout_exc = openai.APITimeoutError(request=dummy_req)  # type: ignore[arg-type]
    mock_client.chat.completions.create.side_effect = timeout_exc

    req = LLMRequest(prompt="Test prompt")
    with pytest.raises(LLMTimeoutError) as exc_info:
        await openai_provider.generate(req)

    assert exc_info.value.retryable is True


def test_sanitize_error_message() -> None:
    """Verify secrets and bearer tokens are masked from error messages."""
    raw = "Error authenticating with Bearer eyJhbGciOi... and sk-proj-1234567890abcdef123456"
    sanitized = sanitize_error_message(raw)
    assert "sk-proj-1234567890abcdef123456" not in sanitized
    assert "Bearer" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_calculate_openai_cost() -> None:
    """Verify cost calculation matches official pricing rates and returns None for unknown models."""
    # gpt-4o: prompt $2.50 / 1M, completion $10.00 / 1M
    cost = calculate_openai_cost(
        "gpt-4o", prompt_tokens=1_000_000, completion_tokens=1_000_000
    )
    assert cost == 12.50

    # gpt-4o-mini: prompt $0.15 / 1M, completion $0.60 / 1M
    cost_mini = calculate_openai_cost(
        "gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000
    )
    assert cost_mini == 0.75

    # Unknown model must return None (never fabricated or guessed)
    cost_unknown = calculate_openai_cost(
        "custom-finetuned-llama", prompt_tokens=1000, completion_tokens=500
    )
    assert cost_unknown is None


def test_llm_service_provider_resolution() -> None:
    """Verify LLMService resolves MockLLMProvider when unconfigured, and OpenAILLMProvider when configured."""
    # 1. Unset API key falls back safely to MockLLMProvider
    settings_no_key = Settings(LLM_PROVIDER="openai", OPENAI_API_KEY=None)
    service_no_key = LLMService(settings=settings_no_key)
    assert isinstance(service_no_key.provider, MockLLMProvider)

    # 2. Explicit mock provider
    settings_mock = Settings(LLM_PROVIDER="mock")
    service_mock = LLMService(settings=settings_mock)
    assert isinstance(service_mock.provider, MockLLMProvider)

    # 3. Configured OpenAI API key resolves OpenAILLMProvider
    settings_with_key = Settings(
        LLM_PROVIDER="openai",
        OPENAI_API_KEY=SecretStr("sk-dummy-test-key-for-resolution-test-12345"),
        OPENAI_MODEL="gpt-4o",
    )
    service_with_key = LLMService(settings=settings_with_key)
    assert isinstance(service_with_key.provider, OpenAILLMProvider)


def test_llm_diagnostics_safe_masking() -> None:
    """Verify LLM diagnostics expose metadata without revealing secrets."""
    settings = Settings(
        LLM_PROVIDER="openai",
        OPENAI_API_KEY=SecretStr("sk-my-super-secret-production-key-12345"),
        OPENAI_MODEL="gpt-4o",
        LLM_MAX_RETRIES=3,
        LLM_REQUEST_TIMEOUT_SECONDS=45.0,
    )
    diag = settings.llm_diagnostics

    assert diag["provider"] == "openai"
    assert diag["model"] == "gpt-4o"
    assert diag["api_key_configured"] is True
    assert diag["max_retries"] == 3
    assert diag["timeout_seconds"] == 45.0

    # Ensure secret value is nowhere in the dictionary
    serialized = str(diag)
    assert "sk-my-super-secret" not in serialized


def test_openai_provider_missing_key_raises_configuration_error() -> None:
    """Verify OpenAILLMProvider raises WorkflowConfigurationError if initialized without a key."""
    settings = Settings(LLM_PROVIDER="openai", OPENAI_API_KEY=None)
    with pytest.raises(WorkflowConfigurationError) as exc_info:
        OpenAILLMProvider(settings=settings)
    assert "OPENAI_API_KEY" in str(exc_info.value)
