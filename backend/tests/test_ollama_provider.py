"""Unit tests for OllamaLLMProvider, structured outputs, telemetry, and error mapping.

These tests use mocked HTTP responses and do NOT require an active Ollama instance.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.config import Settings
from app.orchestration.errors import (
    InvalidCriticOutputError,
    InvalidPlannerOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.review_plan import ReviewPlan
from app.schemas.verification import CriticStructuredOutput
from app.services.llm.base import LLMRequest
from app.services.llm.ollama_provider import (
    OllamaLLMProvider,
    sanitize_error_message,
)
from app.services.llm.service import LLMService


def _create_mock_ollama_client(handler) -> httpx.AsyncClient:
    """Create an AsyncClient with a custom MockTransport."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")


@pytest.fixture
def default_settings() -> Settings:
    return Settings(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_MODEL="qwen3:4b-instruct",
        LLM_MAX_RETRIES=2,
        OLLAMA_REQUEST_TIMEOUT_SECONDS=10.0,
    )


# 1. Successful text generation test
@pytest.mark.asyncio
async def test_ollama_provider_generate_success(default_settings: Settings) -> None:
    """Verify standard text generation extracts content, usage, and local cost (0.0)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/api/chat" in request.url.path
        body = json.loads(request.read())
        assert body["model"] == "qwen3:4b-instruct"
        assert len(body["messages"]) == 2
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {"role": "assistant", "content": "Review looks solid."},
                "done": True,
                "prompt_eval_count": 120,
                "eval_count": 45,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(
        prompt="Review this file",
        system_prompt="You are a code reviewer",
        model="qwen3:4b-instruct",
    )
    resp = await provider.generate(req)

    assert resp.content == "Review looks solid."
    assert resp.prompt_tokens == 120
    assert resp.completion_tokens == 45
    assert resp.total_tokens == 165
    assert resp.model_name == "qwen3:4b-instruct"
    assert resp.latency_seconds >= 0.0
    assert resp.estimated_cost_usd == 0.0


# 2. Structured response test
@pytest.mark.asyncio
async def test_ollama_provider_generate_structured_planner(
    default_settings: Settings,
) -> None:
    """Verify structured parsing of ReviewPlan contract with JSON schema enforcement."""
    expected_plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
        focus_areas=["Auth", "SQL"],
        target_files=["app/main.py"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        assert "format" in body
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {
                    "role": "assistant",
                    "content": expected_plan.model_dump_json(),
                },
                "done": True,
                "prompt_eval_count": 250,
                "eval_count": 80,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Generate review plan")
    plan, resp = await provider.generate_structured(req, ReviewPlan)

    assert plan.review_scope == "FULL"
    assert "security_agent" in plan.active_agents
    assert resp.prompt_tokens == 250
    assert resp.completion_tokens == 80
    assert resp.total_tokens == 330
    assert resp.estimated_cost_usd == 0.0


# 3. Malformed response test
@pytest.mark.asyncio
async def test_ollama_provider_malformed_json_raises_typed_error(
    default_settings: Settings,
) -> None:
    """Verify malformed JSON response raises InvalidPlannerOutputError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {
                    "role": "assistant",
                    "content": "Not a JSON: {broken",
                },
                "done": True,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Generate plan")
    with pytest.raises(InvalidPlannerOutputError) as exc_info:
        await provider.generate_structured(req, ReviewPlan)

    raw = str(exc_info.value.details.get("raw_output", ""))
    assert "broken" in raw or "broken" in exc_info.value.message


# 4. Schema validation failure test
@pytest.mark.asyncio
async def test_ollama_provider_schema_validation_failure(
    default_settings: Settings,
) -> None:
    """Verify JSON that violates schema types raises InvalidCriticOutputError for Critic schema."""

    def handler(_request: httpx.Request) -> httpx.Response:
        # Invalid: calibrated_confidence is string instead of float, decision is invalid enum
        bad_critic = {
            "decision": "MAYBE",
            "calibrated_confidence": "not-a-float",
            "reasoning": "Inconclusive",
        }
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(bad_critic),
                },
                "done": True,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Verify finding")
    with pytest.raises(InvalidCriticOutputError) as exc_info:
        await provider.generate_structured(req, CriticStructuredOutput)

    assert "CriticStructuredOutput" in exc_info.value.message


# 5. Timeout test
@pytest.mark.asyncio
async def test_ollama_provider_timeout_raises_llm_timeout_error(
    default_settings: Settings,
) -> None:
    """Verify network or request timeout maps to LLMTimeoutError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out after 10s")

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Review massive PR")
    with pytest.raises(LLMTimeoutError) as exc_info:
        await provider.generate(req)

    assert exc_info.value.retryable is True
    assert "timed out" in exc_info.value.message.lower()


# 6. Connection failure test
@pytest.mark.asyncio
async def test_ollama_provider_connection_failure(default_settings: Settings) -> None:
    """Verify unreachable Ollama daemon raises retryable LLMProviderError with guidance."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused to port 11434")

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Test connection")
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate(req)

    assert exc_info.value.retryable is True
    assert "ollama serve" in exc_info.value.message.lower()


# 7. Model not found test (404)
@pytest.mark.asyncio
async def test_ollama_provider_model_not_found_404(default_settings: Settings) -> None:
    """Verify HTTP 404 maps to non-retryable LLMProviderError with ollama pull instruction."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "model 'qwen3:4b-instruct' not found, try pulling it first"},
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Test missing model")
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate(req)

    assert exc_info.value.retryable is False
    assert exc_info.value.details.get("status_code") == 404
    assert "ollama pull" in exc_info.value.message.lower()


# 8. Retry behavior test
@pytest.mark.asyncio
async def test_ollama_provider_retries_on_server_error_and_succeeds(
    default_settings: Settings,
) -> None:
    """Verify provider retries on transient 500 error and returns when successful."""
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, json={"error": "Ollama temporary error"})
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {"role": "assistant", "content": "Recovered from 500."},
                "done": True,
                "prompt_eval_count": 50,
                "eval_count": 20,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Test retry")
    resp = await provider.generate(req)

    assert call_count == 2
    assert resp.content == "Recovered from 500."


# 9. Telemetry accuracy test (no fabrication)
@pytest.mark.asyncio
async def test_ollama_provider_telemetry_fields(default_settings: Settings) -> None:
    """Verify token counts are preserved from Ollama response without fabrication."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {"role": "assistant", "content": "Telemetry check."},
                "done": True,
                "prompt_eval_count": 42,
                "eval_count": 17,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Telemetry prompt")
    resp = await provider.generate(req)

    assert resp.prompt_tokens == 42
    assert resp.completion_tokens == 17
    assert resp.total_tokens == 59
    assert resp.estimated_cost_usd == 0.0


# 10. Configuration and diagnostics test
def test_ollama_configuration_and_diagnostics() -> None:
    """Verify Settings and diagnostics report Ollama metadata safely."""
    settings = Settings(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://192.168.1.50:11434",
        OLLAMA_MODEL="qwen3:4b-instruct",
        LLM_MAX_RETRIES=4,
        LLM_REQUEST_TIMEOUT_SECONDS=90.0,
    )

    diag = settings.llm_diagnostics
    assert diag["provider"] == "ollama"
    assert diag["model"] == "qwen3:4b-instruct"
    assert diag["api_key_configured"] is True
    assert diag["base_url"] == "http://192.168.1.50:11434"
    assert diag["max_retries"] == 4
    assert diag["timeout_seconds"] == 90.0


# 11. Error sanitization test
def test_sanitize_error_message_ollama() -> None:
    """Verify secrets or Bearer tokens are redacted in error messages."""
    raw_error = "Failed to connect to http://remote:11434 with Bearer sk-ant-secret1234567890123"
    sanitized = sanitize_error_message(raw_error)
    assert "sk-ant-secret" not in sanitized
    assert "Bearer" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


# 12. Empty response test
@pytest.mark.asyncio
async def test_ollama_provider_empty_structured_response(
    default_settings: Settings,
) -> None:
    """Verify empty string in structured output raises InvalidPlannerOutputError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {"role": "assistant", "content": ""},
                "done": True,
            },
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Empty test")
    with pytest.raises(InvalidPlannerOutputError) as exc_info:
        await provider.generate_structured(req, ReviewPlan)

    assert "empty" in exc_info.value.message.lower()


# 13. Unexpected response / bad request (400)
@pytest.mark.asyncio
async def test_ollama_provider_bad_request_400(default_settings: Settings) -> None:
    """Verify HTTP 400 maps to non-retryable LLMProviderError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid parameter 'options.temperature'"},
        )

    client = _create_mock_ollama_client(handler)
    provider = OllamaLLMProvider(settings=default_settings, client=client)

    req = LLMRequest(prompt="Bad request test")
    with pytest.raises(LLMProviderError) as exc_info:
        await provider.generate(req)

    assert exc_info.value.retryable is False
    assert exc_info.value.details.get("status_code") == 400


# 14. Provider resolution test
def test_llm_service_resolves_ollama() -> None:
    """Verify LLMService resolves OllamaLLMProvider when LLM_PROVIDER=ollama."""
    settings = Settings(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_MODEL="qwen3:4b-instruct",
    )
    service = LLMService(settings=settings)
    assert isinstance(service.provider, OllamaLLMProvider)
    assert service.provider.default_model == "qwen3:4b-instruct"
    assert service.provider.base_url == "http://localhost:11434"
