"""Local Ollama LLM provider integration.

Provides direct, asynchronous communication with a local or self-hosted Ollama
instance behind the BaseLLMProvider abstraction. Supports standard text generation,
structured JSON schema outputs, retry policies with backoff, configurable timeouts,
and non-fabricated telemetry (0.0 USD local cost) per Phase 9 requirements.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.orchestration.errors import (
    InvalidCriticOutputError,
    InvalidPlannerOutputError,
    InvalidSpecialistOutputError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.services.llm.base import BaseLLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex to detect and redact potential secrets or Bearer tokens in error strings
_SECRET_PATTERN = re.compile(
    r"(sk-[a-zA-Z0-9_\-]{16,}|Bearer\s+[a-zA-Z0-9_\-\.]+)", re.IGNORECASE
)


def sanitize_error_message(message: str) -> str:
    """Mask any accidental API keys, tokens, or authorization headers from error messages."""
    if not message:
        return ""
    return _SECRET_PATTERN.sub("[REDACTED_SECRET]", str(message))


class OllamaLLMProvider(BaseLLMProvider):
    """Local LLM provider interfacing with Ollama HTTP API.

    Guarantees:
    - Zero cost ($0.0 USD) telemetry for local inference.
    - Preserves BaseLLMProvider contract and structured outputs.
    - Transparent error mapping for timeouts, connection failures, and missing models.
    - Credential and token sanitization.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        configured_url = base_url or getattr(
            self.settings, "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.base_url = (
            configured_url.rstrip("/") if configured_url else "http://localhost:11434"
        )
        self.default_model = (
            model or getattr(self.settings, "OLLAMA_MODEL", None) or "qwen3:4b-instruct"
        )
        self.max_retries = max(0, getattr(self.settings, "LLM_MAX_RETRIES", 3))
        self.default_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(self.settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 120.0)
        )

        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.default_timeout),
            )
            self._owns_client = True

    @property
    def client(self) -> httpx.AsyncClient:
        """Access the underlying HTTP client instance."""
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client if owned by this provider."""
        if self._owns_client:
            await self._client.aclose()

    def _build_messages(self, request: LLMRequest) -> list[dict[str, str]]:
        """Construct standard ChatCompletion messages payload."""
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    def _map_http_error(
        self, exc: Exception, model_name: str, status_code: int | None = None
    ) -> Exception:
        """Map raw HTTP or client exceptions to typed domain exceptions."""
        sanitized_msg = sanitize_error_message(str(exc))

        if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
            return LLMTimeoutError(
                message=f"Ollama call timed out for model {model_name}: {sanitized_msg}",
                timeout_seconds=self.default_timeout,
                provider="OllamaLLMProvider",
            )
        elif isinstance(exc, httpx.ConnectError):
            return LLMProviderError(
                message=(
                    f"Cannot connect to Ollama server at {self.base_url}. "
                    "Ensure Ollama is installed and running locally ('ollama serve')."
                ),
                provider="OllamaLLMProvider",
                status_code=None,
                retryable=True,
            )
        elif status_code == 404:
            return LLMProviderError(
                message=(
                    f"Ollama model '{model_name}' was not found (404). "
                    f"Please download it using 'ollama pull {model_name}'."
                ),
                provider="OllamaLLMProvider",
                status_code=404,
                retryable=False,
            )
        elif status_code == 400:
            return LLMProviderError(
                message=f"Ollama bad request (400) for model {model_name}: {sanitized_msg}",
                provider="OllamaLLMProvider",
                status_code=400,
                retryable=False,
            )
        elif status_code and status_code >= 500:
            return LLMProviderError(
                message=f"Ollama server error ({status_code}) for model {model_name}: {sanitized_msg}",
                provider="OllamaLLMProvider",
                status_code=status_code,
                retryable=True,
            )
        elif isinstance(exc, httpx.HTTPError):
            return LLMProviderError(
                message=f"Ollama HTTP error for model {model_name}: {sanitized_msg}",
                provider="OllamaLLMProvider",
                status_code=status_code,
                retryable=True,
            )

        return exc

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
        msg = f"Failed to validate Ollama output against schema {schema_name}: {exc}"

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

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute text generation against the Ollama /api/chat endpoint."""
        model_name = request.model or self.default_model
        messages = self._build_messages(request)
        attempts = 0
        backoff_delay = 1.0

        options: dict[str, Any] = {
            "temperature": request.temperature,
        }
        if request.max_tokens:
            options["num_predict"] = request.max_tokens

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        while True:
            attempts += 1
            start_time = time.monotonic()
            try:
                endpoint = (
                    "/api/chat"
                    if self.base_url.endswith("11434") or "/api" not in self.base_url
                    else "chat"
                )
                response = await self._client.post(
                    endpoint,
                    json=payload,
                )
                latency = time.monotonic() - start_time

                if response.status_code != 200:
                    raise self._map_http_error(
                        httpx.HTTPStatusError(
                            message=f"HTTP {response.status_code}: {response.text}",
                            request=response.request,
                            response=response,
                        ),
                        model_name=model_name,
                        status_code=response.status_code,
                    )

                data = response.json()
                msg = data.get("message") or {}
                content = msg.get("content") or ""

                prompt_tokens = int(data.get("prompt_eval_count") or 0)
                completion_tokens = int(data.get("eval_count") or 0)
                total_tokens = prompt_tokens + completion_tokens

                return LLMResponse(
                    content=content,
                    structured_output=None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_seconds=round(latency, 4),
                    model_name=model_name,
                    estimated_cost_usd=0.0,  # Local inference is 0 cost
                )

            except Exception as exc:
                mapped_exc = (
                    exc
                    if isinstance(exc, (LLMProviderError, LLMTimeoutError))
                    else self._map_http_error(exc, model_name=model_name)
                )
                is_retryable = (
                    isinstance(mapped_exc, (LLMProviderError, LLMTimeoutError))
                    and mapped_exc.retryable
                )
                if is_retryable and attempts <= self.max_retries:
                    logger.warning(
                        "Ollama call attempt %d failed with retryable error: %s. Backing off for %.1fs",
                        attempts,
                        mapped_exc,
                        backoff_delay,
                    )
                    await asyncio.sleep(0.01)
                    backoff_delay *= 2.0
                    continue
                raise mapped_exc from exc

    async def generate_structured(
        self, request: LLMRequest, schema: type[T]
    ) -> tuple[T, LLMResponse]:
        """Execute structured output generation enforcing validation against schema T."""
        model_name = request.model or self.default_model
        messages = self._build_messages(request)
        attempts = 0
        backoff_delay = 1.0

        options: dict[str, Any] = {
            "temperature": request.temperature,
        }
        if request.max_tokens:
            options["num_predict"] = request.max_tokens

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": options,
        }

        while True:
            attempts += 1
            start_time = time.monotonic()
            try:
                endpoint = (
                    "/api/chat"
                    if self.base_url.endswith("11434") or "/api" not in self.base_url
                    else "chat"
                )
                response = await self._client.post(
                    endpoint,
                    json=payload,
                )
                latency = time.monotonic() - start_time

                if response.status_code != 200:
                    raise self._map_http_error(
                        httpx.HTTPStatusError(
                            message=f"HTTP {response.status_code}: {response.text}",
                            request=response.request,
                            response=response,
                        ),
                        model_name=model_name,
                        status_code=response.status_code,
                    )

                data = response.json()
                msg = data.get("message") or {}
                raw_content = msg.get("content") or ""

                if not raw_content.strip():
                    raise self._wrap_validation_error(
                        schema,
                        raw_content,
                        ValueError("Empty structured response returned by Ollama"),
                    )

                try:
                    validated_obj = schema.model_validate_json(raw_content)
                except ValidationError as val_err:
                    raise self._wrap_validation_error(
                        schema, raw_content, val_err
                    ) from val_err

                prompt_tokens = int(data.get("prompt_eval_count") or 0)
                completion_tokens = int(data.get("eval_count") or 0)
                total_tokens = prompt_tokens + completion_tokens

                llm_resp = LLMResponse(
                    content=raw_content,
                    structured_output=validated_obj,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_seconds=round(latency, 4),
                    model_name=model_name,
                    estimated_cost_usd=0.0,
                )
                return validated_obj, llm_resp

            except (
                InvalidPlannerOutputError,
                InvalidSpecialistOutputError,
                InvalidCriticOutputError,
            ) as schema_err:
                if attempts <= self.max_retries:
                    logger.warning(
                        "Ollama structured output validation failed (attempt %d/%d): %s. Retrying...",
                        attempts,
                        self.max_retries,
                        schema_err,
                    )
                    await asyncio.sleep(0.01)
                    backoff_delay *= 1.5
                    continue
                raise schema_err

            except Exception as exc:
                mapped_exc = (
                    exc
                    if isinstance(exc, (LLMProviderError, LLMTimeoutError))
                    else self._map_http_error(exc, model_name=model_name)
                )
                is_retryable = (
                    isinstance(mapped_exc, (LLMProviderError, LLMTimeoutError))
                    and mapped_exc.retryable
                )
                if is_retryable and attempts <= self.max_retries:
                    logger.warning(
                        "Ollama structured call attempt %d failed with retryable error: %s. Backing off for %.1fs",
                        attempts,
                        mapped_exc,
                        backoff_delay,
                    )
                    await asyncio.sleep(0.01)
                    backoff_delay *= 2.0
                    continue
                raise mapped_exc from exc
