"""Unit tests for the LLMService abstraction, MockLLMProvider, and structured validation."""

import pytest
from app.orchestration.errors import (
    InvalidPlannerOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.review_plan import ReviewPlan
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService


@pytest.mark.asyncio
async def test_mock_provider_generate_text() -> None:
    """Verify standard text generation with the mock provider."""
    provider = MockLLMProvider(default_response="Generated review comment")
    service = LLMService(provider=provider)

    resp = await service.generate(prompt="Review this code")

    assert resp.content == "Generated review comment"
    assert resp.total_tokens > 0
    assert provider.call_count == 1
    assert len(provider.recorded_requests) == 1
    assert provider.recorded_requests[0].prompt == "Review this code"


@pytest.mark.asyncio
async def test_mock_provider_structured_valid_object() -> None:
    """Verify structured output generation using a ReviewPlan model instance."""
    expected_plan = ReviewPlan(
        review_scope="FULL",
        active_agents=["security_agent", "bug_logic_agent"],
        focus_areas=["SQL Injection", "Boundary checks"],
        target_files=["backend/app/db.py"],
    )
    provider = MockLLMProvider(default_response=expected_plan)
    service = LLMService(provider=provider)

    plan, resp = await service.generate_structured(
        prompt="Create plan",
        schema=ReviewPlan,
    )

    assert plan.review_scope == "FULL"
    assert "security_agent" in plan.active_agents
    assert plan.target_files == ["backend/app/db.py"]
    assert resp.structured_output == plan


@pytest.mark.asyncio
async def test_mock_provider_structured_from_dict() -> None:
    """Verify structured output parsing from a dictionary payload."""
    plan_dict = {
        "review_scope": "FOCUSED",
        "active_agents": ["security_agent"],
        "focus_areas": ["Authentication"],
        "target_files": ["backend/app/auth.py"],
        "is_large_pr": False,
    }
    provider = MockLLMProvider(default_response=plan_dict)
    service = LLMService(provider=provider)

    plan, _ = await service.generate_structured(
        prompt="Create focused plan",
        schema=ReviewPlan,
    )

    assert plan.review_scope == "FOCUSED"
    assert plan.active_agents == ["security_agent"]


@pytest.mark.asyncio
async def test_mock_provider_structured_from_json_string() -> None:
    """Verify structured output parsing from a valid JSON string."""
    json_str = '{"review_scope": "SECURITY_ONLY", "active_agents": ["security_agent"]}'
    provider = MockLLMProvider(default_response=json_str)
    service = LLMService(provider=provider)

    plan, _ = await service.generate_structured(
        prompt="Security plan",
        schema=ReviewPlan,
    )

    assert plan.review_scope == "SECURITY_ONLY"


@pytest.mark.asyncio
async def test_mock_provider_malformed_json_raises_invalid_planner_output() -> None:
    """Verify that non-JSON strings raise InvalidPlannerOutputError."""
    malformed = "Here is your plan: {invalid json content...}"
    provider = MockLLMProvider(default_response=malformed)
    service = LLMService(provider=provider)

    with pytest.raises(InvalidPlannerOutputError, match="malformed non-JSON"):
        await service.generate_structured(prompt="Plan", schema=ReviewPlan)


@pytest.mark.asyncio
async def test_mock_provider_schema_mismatch_raises_invalid_planner_output() -> None:
    """Verify that JSON missing required validation constraints raises InvalidPlannerOutputError."""
    # Blank review_scope violates validator on ReviewPlan
    invalid_plan = {"review_scope": "   ", "active_agents": []}
    provider = MockLLMProvider(default_response=invalid_plan)
    service = LLMService(provider=provider)

    with pytest.raises(InvalidPlannerOutputError):
        await service.generate_structured(prompt="Plan", schema=ReviewPlan)


@pytest.mark.asyncio
async def test_llm_service_timeout_handling() -> None:
    """Verify that timeouts during LLM calls raise LLMTimeoutError."""
    # Simulate high latency with small timeout
    provider = MockLLMProvider(default_response="hello", simulated_latency=0.5)
    service = LLMService(provider=provider, default_timeout_seconds=0.05)

    with pytest.raises(LLMTimeoutError, match="timed out"):
        await service.generate(prompt="Long running call")


@pytest.mark.asyncio
async def test_llm_service_provider_error_handling() -> None:
    """Verify that simulated provider exceptions are translated to LLMProviderError."""
    simulated_err = RuntimeError("External API 503 Service Unavailable")
    provider = MockLLMProvider(should_raise=simulated_err)
    service = LLMService(provider=provider)

    with pytest.raises(LLMProviderError, match="503 Service Unavailable"):
        await service.generate(prompt="Call that will fail")


@pytest.mark.asyncio
async def test_mock_provider_response_sequence_for_retry() -> None:
    """Verify that sequential responses can simulate a failure followed by success."""
    valid_plan = ReviewPlan(review_scope="FULL", active_agents=["bug_logic_agent"])
    timeout_err = LLMTimeoutError(message="Temporary timeout", timeout_seconds=1.0)

    provider = MockLLMProvider(response_sequence=[timeout_err, valid_plan])
    service = LLMService(provider=provider)

    # First attempt fails with timeout
    with pytest.raises(LLMTimeoutError):
        await service.generate_structured(prompt="Plan attempt 1", schema=ReviewPlan)

    # Second attempt succeeds
    plan, _ = await service.generate_structured(
        prompt="Plan attempt 2", schema=ReviewPlan
    )
    assert plan.review_scope == "FULL"
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_mock_provider_reset_and_generate_variants() -> None:
    """Verify mock provider reset and handling of None/string responses."""
    provider = MockLLMProvider(default_response=None)
    service = LLMService(provider=provider)

    resp1 = await service.generate(prompt="Prompt 1")
    assert resp1.content == "{}"
    assert provider.call_count == 1

    provider.reset()
    assert provider.call_count == 0
    assert len(provider.recorded_requests) == 0

    # With sequence containing an Exception
    provider.response_sequence = [RuntimeError("Boom")]
    with pytest.raises(LLMProviderError, match="Boom"):
        await service.generate(prompt="Fail")


@pytest.mark.asyncio
async def test_mock_provider_structured_unsupported_type() -> None:
    """Verify unsupported mock structured response raises InvalidPlannerOutputError."""
    provider = MockLLMProvider(default_response=12345)
    service = LLMService(provider=provider)

    with pytest.raises(
        InvalidPlannerOutputError, match="Unsupported mock response type"
    ):
        await service.generate_structured(prompt="test", schema=ReviewPlan)


@pytest.mark.asyncio
async def test_mock_provider_structured_with_sequence_exception() -> None:
    """Verify sequence containing an exception raises in generate_structured."""
    provider = MockLLMProvider(response_sequence=[RuntimeError("Structured Boom")])
    service = LLMService(provider=provider)

    with pytest.raises(LLMProviderError, match="Structured Boom"):
        await service.generate_structured(prompt="test", schema=ReviewPlan)


@pytest.mark.asyncio
async def test_llm_service_default_provider_resolution() -> None:
    """Verify LLMService defaults to MockLLMProvider cleanly."""
    service = LLMService()
    assert isinstance(service.provider, MockLLMProvider)
