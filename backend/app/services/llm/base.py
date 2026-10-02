"""Base abstractions and interfaces for the LLM service layer.

Decouples agent logic (Planner, Specialists, Critic) from concrete LLM vendor SDKs,
satisfying Architecture Rule 6: 'LLM calls must be isolated behind service interfaces.'
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T", bound=BaseModel)


class LLMRequest(BaseModel):
    """Normalized specification for an LLM generation or structured output request."""

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(description="User prompt text submitted to the model")
    system_prompt: str | None = Field(
        default=None, description="System instructions guiding model persona and rules"
    )
    temperature: float = Field(
        default=0.1, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_tokens: int | None = Field(
        default=None, ge=1, description="Upper bound on completion tokens generated"
    )
    model: str | None = Field(
        default=None, description="Optional model identifier override"
    )


class LLMResponse(BaseModel):
    """Normalized metadata and content returned by an LLM provider."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(description="Raw text content produced by the model")
    structured_output: Any | None = Field(
        default=None, description="Deserialized structured data if requested"
    )
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_seconds: float = Field(default=0.0, ge=0.0)
    model_name: str = Field(default="unknown")


class BaseLLMProvider(ABC):
    """Abstract interface for all model providers (Mock, OpenAI, Anthropic, Gemini)."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute a text generation request asynchronously."""
        ...

    @abstractmethod
    async def generate_structured(
        self, request: LLMRequest, schema: type[T]
    ) -> tuple[T, LLMResponse]:
        """Execute a structured output request enforcing validation against schema T."""
        ...
