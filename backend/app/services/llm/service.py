"""LLM Service domain layer managing provider delegation, retries, timeouts, and structured validation.

Provides a unified interface for agent nodes while isolating all provider credentials
and concrete vendor SDK calls per Architecture Rule 6 and 10.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.orchestration.errors import (
    InvalidPlannerOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.services.llm.base import BaseLLMProvider, LLMRequest, LLMResponse
from app.services.llm.mock_provider import MockLLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMService:
    """Domain service managing LLM generation and structured Pydantic extraction.

    Enforces configurable timeouts, structured validation, error mapping,
    and telemetry without exposing credentials to agents or workflows.
    """

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        settings: Settings | None = None,
        default_timeout_seconds: float = 60.0,
    ) -> None:
        self.settings = settings or get_settings()
        self.default_timeout_seconds = default_timeout_seconds

        if provider is not None:
            self._provider = provider
        else:
            self._provider = self._resolve_provider_from_settings()

    def _resolve_provider_from_settings(self) -> BaseLLMProvider:
        """Resolve the appropriate provider implementation based on configuration."""
        provider_name = (self.settings.LLM_PROVIDER or "mock").strip().lower()

        if provider_name == "mock":
            return MockLLMProvider()

        # In Phase 3.1, real external providers are not connected without credentials.
        # Fall back safely to MockLLMProvider if no valid external provider is configured.
        logger.info(
            "Configured LLM provider '%s' not yet active; utilizing MockLLMProvider",
            provider_name,
        )
        return MockLLMProvider()

    @property
    def provider(self) -> BaseLLMProvider:
        """Access the underlying provider instance."""
        return self._provider

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Execute text generation with bounded execution time and error translation."""
        effective_timeout = timeout_seconds or self.default_timeout_seconds
        req = LLMRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature
            if temperature is not None
            else getattr(self.settings, "LLM_TEMPERATURE", 0.1),
            max_tokens=max_tokens,
            model=model,
        )

        start_time = time.monotonic()
        try:
            async with asyncio.timeout(effective_timeout):
                resp = await self._provider.generate(req)
                return resp
        except TimeoutError as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "LLM call timed out after %.2fs (threshold=%.2fs)",
                duration,
                effective_timeout,
            )
            raise LLMTimeoutError(
                message=f"LLM request timed out after {effective_timeout:.1f}s",
                timeout_seconds=effective_timeout,
                provider=self._provider.__class__.__name__,
            ) from exc
        except (LLMTimeoutError, LLMProviderError, InvalidPlannerOutputError):
            raise
        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "LLM provider failed after %.2fs: %s",
                duration,
                exc,
                exc_info=True,
            )
            raise LLMProviderError(
                message=f"LLM provider failure: {exc}",
                provider=self._provider.__class__.__name__,
            ) from exc

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[T, LLMResponse]:
        """Execute structured output generation, enforcing schema T on the response."""
        effective_timeout = timeout_seconds or self.default_timeout_seconds
        req = LLMRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature
            if temperature is not None
            else getattr(self.settings, "LLM_TEMPERATURE", 0.1),
            max_tokens=max_tokens,
            model=model,
        )

        start_time = time.monotonic()
        try:
            async with asyncio.timeout(effective_timeout):
                validated_data, resp = await self._provider.generate_structured(
                    req, schema
                )
                duration = time.monotonic() - start_time
                logger.info(
                    "Structured LLM generation succeeded for %s: duration=%.2fs, tokens=%d",
                    schema.__name__,
                    duration,
                    resp.total_tokens,
                )
                return validated_data, resp
        except TimeoutError as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Structured LLM call timed out after %.2fs (threshold=%.2fs)",
                duration,
                effective_timeout,
            )
            raise LLMTimeoutError(
                message=f"Structured LLM request timed out after {effective_timeout:.1f}s",
                timeout_seconds=effective_timeout,
                provider=self._provider.__class__.__name__,
            ) from exc
        except (LLMTimeoutError, LLMProviderError, InvalidPlannerOutputError):
            raise
        except ValidationError as exc:
            raise InvalidPlannerOutputError(
                message=f"LLM output failed Pydantic validation for {schema.__name__}: {exc}",
                validation_errors=exc.errors(),  # type: ignore[arg-type]
            ) from exc
        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Structured LLM call failed after %.2fs: %s",
                duration,
                exc,
                exc_info=True,
            )
            raise LLMProviderError(
                message=f"LLM provider failure during structured generation: {exc}",
                provider=self._provider.__class__.__name__,
            ) from exc
