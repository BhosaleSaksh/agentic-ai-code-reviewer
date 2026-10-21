"""Controlled live LLM integration test executing only when explicitly configured.

Guarantees:
- Ordinary unit tests and CI never make external API calls (RUN_LLM_INTEGRATION_TESTS unset).
- When enabled by a developer with local credentials in .env:
  - Validates real provider connection to OpenAI
  - Validates structured output generation
  - Validates token/latency/cost telemetry
  - Never prints or leaks API keys into output, logs, or assertions.
"""

from __future__ import annotations

import os

import pytest
from app.core.config import Settings
from app.schemas.review_plan import ReviewPlan
from app.schemas.verification import CriticStructuredOutput
from app.services.llm.openai_provider import OpenAILLMProvider
from app.services.llm.service import LLMService
from pydantic import SecretStr

_RUN_LIVE = os.getenv("RUN_LLM_INTEGRATION_TESTS", "").strip().lower() in (
    "true",
    "1",
    "yes",
) and bool(os.getenv("OPENAI_API_KEY", "").strip())

pytestmark = pytest.mark.skipif(
    not _RUN_LIVE,
    reason="Controlled live test skipped. Enable with RUN_LLM_INTEGRATION_TESTS=true and OPENAI_API_KEY.",
)


@pytest.fixture
def live_llm_service() -> LLMService:
    raw_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    settings = Settings(
        LLM_PROVIDER="openai",
        OPENAI_API_KEY=SecretStr(raw_key),
        OPENAI_MODEL=model,
        LLM_REQUEST_TIMEOUT_SECONDS=45.0,
        LLM_MAX_RETRIES=2,
    )
    return LLMService(settings=settings)


@pytest.mark.asyncio
async def test_live_openai_text_generation(live_llm_service: LLMService) -> None:
    """Validate real text generation against OpenAI API."""
    assert isinstance(live_llm_service.provider, OpenAILLMProvider)

    resp = await live_llm_service.generate(
        prompt="Respond with exactly 'PONG' and nothing else.",
        system_prompt="You are a ping-pong service.",
        temperature=0.0,
    )

    assert "PONG" in resp.content.upper()
    assert resp.prompt_tokens > 0
    assert resp.completion_tokens > 0
    assert resp.total_tokens == resp.prompt_tokens + resp.completion_tokens
    assert resp.latency_seconds > 0.0
    if resp.estimated_cost_usd is not None:
        assert resp.estimated_cost_usd >= 0.0


@pytest.mark.asyncio
async def test_live_openai_structured_review_plan(
    live_llm_service: LLMService,
) -> None:
    """Validate real structured output parsing for ReviewPlan against OpenAI API."""
    prompt = (
        "We have a PR modifying backend/app/auth.py adding password hashing functions. "
        "Create a review plan choosing active agents from [security_agent, bug_logic_agent]."
    )

    plan, resp = await live_llm_service.generate_structured(
        prompt=prompt,
        schema=ReviewPlan,
        system_prompt="You are a lead code review planner.",
        temperature=0.1,
    )

    assert isinstance(plan, ReviewPlan)
    assert plan.review_scope in {"FULL", "FOCUSED", "SECURITY_ONLY", "SKIP"}
    assert any(a in plan.active_agents for a in ["security_agent", "bug_logic_agent"])
    assert resp.total_tokens > 0
    assert resp.latency_seconds > 0.0


@pytest.mark.asyncio
async def test_live_openai_structured_critic_verification(
    live_llm_service: LLMService,
) -> None:
    """Validate real structured output parsing for CriticStructuredOutput against OpenAI API."""
    prompt = (
        "Candidate finding: SQL injection in backend/app/db.py at line 10. "
        "Diff evidence: + query = f'SELECT * FROM users WHERE id = {user_input}'\n"
        "Evaluate this finding and verify whether it is a real vulnerability."
    )

    result, resp = await live_llm_service.generate_structured(
        prompt=prompt,
        schema=CriticStructuredOutput,
        system_prompt="You are a code review verification critic.",
        temperature=0.1,
    )

    assert isinstance(result, CriticStructuredOutput)
    assert result.decision in {"VERIFIED", "REJECTED"}
    assert 0.0 <= result.calibrated_confidence <= 1.0
    assert resp.total_tokens > 0
