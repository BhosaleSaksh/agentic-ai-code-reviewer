"""Controlled live Ollama integration test executing only when explicitly configured.

Guarantees:
- Ordinary unit tests and CI never make external or local network calls.
- When enabled by a developer with RUN_LLM_INTEGRATION_TESTS=true and an active Ollama instance:
  - Validates real provider connection to local Ollama daemon
  - Validates text generation and model inference
  - Validates structured output generation
  - Validates token/latency telemetry and $0.0 local cost
"""

from __future__ import annotations

import os

import httpx
import pytest
from app.core.config import Settings
from app.schemas.review_plan import ReviewPlan
from app.schemas.verification import CriticStructuredOutput
from app.services.llm.ollama_provider import OllamaLLMProvider
from app.services.llm.service import LLMService

_ENV_FLAG = os.getenv("RUN_LLM_INTEGRATION_TESTS", "").strip().lower() in (
    "true",
    "1",
    "yes",
)

_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")


def _is_ollama_reachable() -> bool:
    """Check if the local Ollama daemon is reachable without hanging."""
    if not _ENV_FLAG:
        return False
    try:
        resp = httpx.get(f"{_BASE_URL}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


_RUN_OLLAMA_LIVE = _ENV_FLAG and _is_ollama_reachable()

pytestmark = pytest.mark.skipif(
    not _RUN_OLLAMA_LIVE,
    reason=(
        "Controlled live Ollama test skipped. "
        "Enable with RUN_LLM_INTEGRATION_TESTS=true and ensure Ollama is running on port 11434."
    ),
)


@pytest.fixture
def live_ollama_service() -> LLMService:
    settings = Settings(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=_BASE_URL,
        OLLAMA_MODEL=_MODEL,
        OLLAMA_REQUEST_TIMEOUT_SECONDS=60.0,
        LLM_MAX_RETRIES=1,
    )
    return LLMService(settings=settings)


@pytest.mark.asyncio
async def test_live_ollama_text_generation(live_ollama_service: LLMService) -> None:
    """Validate real text generation against local Ollama daemon."""
    assert isinstance(live_ollama_service.provider, OllamaLLMProvider)

    resp = await live_ollama_service.generate(
        prompt="Reply with exactly the word 'PONG' and nothing else.",
        system_prompt="You are a healthcheck bot.",
        temperature=0.0,
    )

    assert "PONG" in resp.content.upper()
    assert resp.prompt_tokens >= 0
    assert resp.completion_tokens >= 0
    assert resp.latency_seconds > 0.0
    assert resp.estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_live_ollama_structured_review_plan(
    live_ollama_service: LLMService,
) -> None:
    """Validate real structured generation against local Ollama daemon enforcing ReviewPlan contract."""
    prompt = (
        "Create a review plan for a pull request that changes 1 file: backend/app/auth.py. "
        "Review scope should be FULL or SECURITY_ONLY."
    )
    plan, resp = await live_ollama_service.generate_structured(
        prompt=prompt,
        schema=ReviewPlan,
        system_prompt="You are a code review planning agent. Output structured JSON adhering to the ReviewPlan schema.",
        temperature=0.1,
    )

    assert isinstance(plan, ReviewPlan)
    assert plan.review_scope in ("FULL", "TARGETED", "SECURITY_ONLY")
    assert isinstance(plan.active_agents, list)
    assert resp.structured_output == plan
    assert resp.estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_live_ollama_structured_critic(
    live_ollama_service: LLMService,
) -> None:
    """Validate real structured Critic verification output against local Ollama daemon."""
    prompt = (
        "Verify candidate finding: Line 25 in backend/app/auth.py uses md5 for password hashing. "
        "Evidence from bandit corroborates B303 weak cryptographic hash. "
        "Evaluate if finding is VERIFIED, calibrate confidence, and give reasoning."
    )
    critic_output, resp = await live_ollama_service.generate_structured(
        prompt=prompt,
        schema=CriticStructuredOutput,
        system_prompt="You are a code review verification Critic. Output JSON adhering to CriticStructuredOutput.",
        temperature=0.0,
    )

    assert isinstance(critic_output, CriticStructuredOutput)
    assert critic_output.decision in ("VERIFIED", "REJECTED", "INSUFFICIENT_EVIDENCE")
    assert 0.0 <= critic_output.calibrated_confidence <= 1.0
    assert resp.estimated_cost_usd == 0.0
