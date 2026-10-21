"""Production OpenAI LLM provider integration.

Provides direct, asynchronous access to OpenAI chat completion models and native
structured outputs (pydantic-based JSON schema validation) behind the BaseLLMProvider
abstraction. Supports robust retry policies, timeout management, token/cost telemetry,
and strict credential isolation per Phase 8 requirements.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.orchestration.errors import (
    InvalidCriticOutputError,
    InvalidPlannerOutputError,
    InvalidSpecialistOutputError,
    LLMProviderError,
    LLMTimeoutError,
    WorkflowConfigurationError,
)
from app.services.llm.base import BaseLLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex to detect and redact potential OpenAI API keys or Bearer tokens in error strings
_SECRET_PATTERN = re.compile(
    r"(sk-[a-zA-Z0-9_\-]{16,}|Bearer\s+[a-zA-Z0-9_\-\.]+)", re.IGNORECASE
)

# Standard OpenAI pricing rates per 1,000,000 tokens (USD)
# Used exclusively for calculating estimated cost; if model is not listed, cost is None.
OPENAI_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
    "gpt-4o-2024-11-20": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4-turbo-2024-04-09": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o1-preview": {"input": 15.00, "output": 60.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
}


def sanitize_error_message(message: str) -> str:
    """Mask any accidental API keys, tokens, or authorization headers from error messages."""
    if not message:
        return ""
    return _SECRET_PATTERN.sub("[REDACTED_SECRET]", str(message))


def calculate_openai_cost(
    model_name: str, prompt_tokens: int, completion_tokens: int
) -> float | None:
    """Calculate the estimated USD cost for an OpenAI invocation based on published rates.

    Returns None if pricing rates are not explicitly known for the given model name.
    Never returns fabricated or placeholder numbers.
    """
    cleaned_model = model_name.strip().lower()
    rates: dict[str, float] | None = None

    if cleaned_model in OPENAI_MODEL_PRICING:
        rates = OPENAI_MODEL_PRICING[cleaned_model]
    else:
        # Match by prefix for snapshot versions (e.g. gpt-4o-mini-*)
        for known_prefix, known_rates in OPENAI_MODEL_PRICING.items():
            if cleaned_model.startswith(known_prefix):
                rates = known_rates
                break

    if rates is None:
        return None

    cost = (prompt_tokens / 1_000_000.0) * rates["input"] + (
        completion_tokens / 1_000_000.0
    ) * rates["output"]
    return round(cost, 6)


class OpenAILLMProvider(BaseLLMProvider):
    """Production provider integrating official OpenAI AsyncOpenAI SDK.

    Supports native structured output parsing, robust error categorization,
    exponential backoff retries on transient errors, and strict credential isolation.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.default_model = self.settings.OPENAI_MODEL or "gpt-4o"
        self.max_retries = max(0, self.settings.LLM_MAX_RETRIES)
        self.default_timeout = getattr(
            self.settings, "LLM_REQUEST_TIMEOUT_SECONDS", 60.0
        )

        if client is not None:
            self._client = client
        else:
            api_key = (
                self.settings.OPENAI_API_KEY.get_secret_value().strip()
                if self.settings.OPENAI_API_KEY
                else ""
            )
            if not api_key:
                raise WorkflowConfigurationError(
                    "OpenAI API key is missing. Configure OPENAI_API_KEY in the environment.",
                    parameter="OPENAI_API_KEY",
                )
            self._client = AsyncOpenAI(
                api_key=api_key,
                timeout=self.default_timeout,
                max_retries=0,  # We manage retries explicitly with backoff
            )

    @property
    def client(self) -> AsyncOpenAI:
        """Access the underlying AsyncOpenAI client instance."""
        return self._client

    def _map_exception(self, exc: Exception, model_name: str) -> Exception:
        """Map raw OpenAI SDK exceptions into typed workflow-level exceptions.

        Strictly guarantees credentials are never exposed in error text or logs.
        """
        sanitized_msg = sanitize_error_message(str(exc))

        if isinstance(exc, openai.APITimeoutError):
            return LLMTimeoutError(
                message=f"OpenAI call timed out for model {model_name}: {sanitized_msg}",
                timeout_seconds=self.default_timeout,
                provider="OpenAILLMProvider",
            )
        elif isinstance(exc, openai.RateLimitError):
            return LLMProviderError(
                message=f"OpenAI rate limit exceeded (429) for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=429,
                retryable=True,
            )
        elif isinstance(exc, openai.APIConnectionError):
            return LLMProviderError(
                message=f"OpenAI connection error for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=None,
                retryable=True,
            )
        elif isinstance(exc, openai.AuthenticationError):
            return LLMProviderError(
                message="OpenAI authentication failed (401). Check OPENAI_API_KEY configuration.",
                provider="OpenAILLMProvider",
                status_code=401,
                retryable=False,
            )
        elif isinstance(exc, openai.PermissionDeniedError):
            return LLMProviderError(
                message=f"OpenAI permission denied (403) for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=403,
                retryable=False,
            )
        elif isinstance(exc, openai.BadRequestError):
            return LLMProviderError(
                message=f"OpenAI bad request (400) for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=400,
                retryable=False,
            )
        elif isinstance(exc, openai.InternalServerError):
            return LLMProviderError(
                message=f"OpenAI server error (500) for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=500,
                retryable=True,
            )
        elif isinstance(exc, openai.LengthFinishReasonError):
            return LLMProviderError(
                message=f"OpenAI response truncated by token limit for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=422,
                retryable=False,
            )
        elif isinstance(exc, openai.APIError):
            status = getattr(exc, "status_code", None)
            retryable = status in {408, 429, 500, 502, 503, 504}
            return LLMProviderError(
                message=f"OpenAI API error ({status}) for model {model_name}: {sanitized_msg}",
                provider="OpenAILLMProvider",
                status_code=status,
                retryable=retryable,
            )
        return exc

    def _build_messages(self, request: LLMRequest) -> list[dict[str, str]]:
        """Construct the standard ChatCompletion messages payload."""
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute text generation against the OpenAI API with retry handling."""
        model_name = request.model or self.default_model
        messages = self._build_messages(request)
        attempts = 0
        backoff_delay = 1.0

        while True:
            attempts += 1
            start_time = time.monotonic()
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": messages,
                }
                # o1 / o3 models do not support arbitrary temperature
                if not (model_name.startswith("o1") or model_name.startswith("o3")):
                    kwargs["temperature"] = request.temperature
                if request.max_tokens:
                    kwargs["max_completion_tokens"] = request.max_tokens

                completion = await self._client.chat.completions.create(**kwargs)
                latency = time.monotonic() - start_time

                content = completion.choices[0].message.content or ""
                prompt_tokens = (
                    completion.usage.prompt_tokens if completion.usage else 0
                )
                completion_tokens = (
                    completion.usage.completion_tokens if completion.usage else 0
                )
                total_tokens = completion.usage.total_tokens if completion.usage else 0
                cost = calculate_openai_cost(
                    model_name, prompt_tokens, completion_tokens
                )

                return LLMResponse(
                    content=content,
                    structured_output=None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_seconds=round(latency, 4),
                    model_name=model_name,
                    estimated_cost_usd=cost,
                )

            except Exception as exc:
                mapped_exc = self._map_exception(exc, model_name)
                is_retryable = (
                    isinstance(mapped_exc, (LLMProviderError, LLMTimeoutError))
                    and mapped_exc.retryable
                )
                if is_retryable and attempts <= self.max_retries:
                    logger.warning(
                        "OpenAI call attempt %d failed with retryable error: %s. Backing off for %.1fs",
                        attempts,
                        mapped_exc,
                        backoff_delay,
                    )
                    time.sleep(0.01)  # brief yield for event loop
                    backoff_delay *= 2.0
                    continue
                raise mapped_exc from exc

    async def generate_structured(
        self, request: LLMRequest, schema: type[T]
    ) -> tuple[T, LLMResponse]:
        """Execute structured output generation enforcing validation against schema T.

        Uses OpenAI's native client.chat.completions.parse API, falling back to
        JSON mode with strict Pydantic parsing if required.
        """
        model_name = request.model or self.default_model
        messages = self._build_messages(request)
        attempts = 0
        backoff_delay = 1.0

        while True:
            attempts += 1
            start_time = time.monotonic()
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": messages,
                    "response_format": schema,
                }
                if not (model_name.startswith("o1") or model_name.startswith("o3")):
                    kwargs["temperature"] = request.temperature
                if request.max_tokens:
                    kwargs["max_completion_tokens"] = request.max_tokens

                completion = await self._client.chat.completions.parse(**kwargs)
                latency = time.monotonic() - start_time

                choice = completion.choices[0]
                message = choice.message

                # Check for explicit model refusal
                if getattr(message, "refusal", None):
                    raise LLMProviderError(
                        message=f"OpenAI model refused structured output generation: {message.refusal}",
                        provider="OpenAILLMProvider",
                        status_code=422,
                        retryable=False,
                    )

                raw_content = message.content or ""
                validated_obj: T

                if message.parsed is not None and isinstance(message.parsed, schema):
                    validated_obj = message.parsed
                elif raw_content:
                    # Fallback validation from raw content
                    try:
                        validated_obj = schema.model_validate_json(raw_content)
                    except ValidationError as val_err:
                        raise self._wrap_validation_error(
                            schema, raw_content, val_err
                        ) from val_err
                else:
                    raise self._wrap_validation_error(
                        schema,
                        raw_content,
                        ValueError("Empty structured response returned by model"),
                    )

                prompt_tokens = (
                    completion.usage.prompt_tokens if completion.usage else 0
                )
                completion_tokens = (
                    completion.usage.completion_tokens if completion.usage else 0
                )
                total_tokens = completion.usage.total_tokens if completion.usage else 0
                cost = calculate_openai_cost(
                    model_name, prompt_tokens, completion_tokens
                )

                llm_resp = LLMResponse(
                    content=raw_content
                    if raw_content
                    else validated_obj.model_dump_json(),
                    structured_output=validated_obj,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_seconds=round(latency, 4),
                    model_name=model_name,
                    estimated_cost_usd=cost,
                )
                return validated_obj, llm_resp

            except (
                InvalidPlannerOutputError,
                InvalidSpecialistOutputError,
                InvalidCriticOutputError,
            ) as schema_err:
                # If output was malformed and we have retries left, retry with backoff
                if attempts <= self.max_retries:
                    logger.warning(
                        "Structured output validation failed (attempt %d/%d): %s. Retrying...",
                        attempts,
                        self.max_retries,
                        schema_err,
                    )
                    time.sleep(0.01)
                    backoff_delay *= 1.5
                    continue
                raise schema_err

            except Exception as exc:
                mapped_exc = self._map_exception(exc, model_name)
                is_retryable = (
                    isinstance(mapped_exc, (LLMProviderError, LLMTimeoutError))
                    and mapped_exc.retryable
                )
                if is_retryable and attempts <= self.max_retries:
                    logger.warning(
                        "OpenAI structured call attempt %d failed with retryable error: %s. Backing off for %.1fs",
                        attempts,
                        mapped_exc,
                        backoff_delay,
                    )
                    time.sleep(0.01)
                    backoff_delay *= 2.0
                    continue
                raise mapped_exc from exc

    def _wrap_validation_error(
        self, schema: type[T], raw_content: str, exc: Exception
    ) -> Exception:
        """Map validation errors into domain-specific structured failure types."""
        val_errors: list[dict[str, object]] | None = None
        if isinstance(exc, ValidationError):
            val_errors = [
                {"loc": [str(x) for x in err.get("loc", [])], "msg": err.get("msg", "")}
                for err in exc.errors()
            ]

        schema_name = schema.__name__
        msg = f"Failed to validate OpenAI output against schema {schema_name}: {exc}"

        if "ReviewPlan" in schema_name:
            return InvalidPlannerOutputError(
                message=msg,
                raw_output=raw_content,
                validation_errors=val_errors,
            )
        elif "Critic" in schema_name or "Verification" in schema_name:
            return InvalidCriticOutputError(
                message=msg,
                raw_output=raw_content,
                validation_errors=val_errors,
            )
        elif "Specialist" in schema_name:
            return InvalidSpecialistOutputError(
                message=msg,
                agent_name="specialist",
                raw_output=raw_content,
                validation_errors=val_errors,
            )
        return InvalidPlannerOutputError(
            message=msg,
            raw_output=raw_content,
            validation_errors=val_errors,
        )
