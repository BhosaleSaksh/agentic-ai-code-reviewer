"""Deterministic mock and fake LLM provider for unit, integration, and offline testing.

Guarantees 100% test isolation with zero dependencies on external LLM vendors,
network connectivity, or production API keys per Section 7 and 19 of the project spec.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.orchestration.errors import (
    InvalidPlannerOutputError,
)
from app.services.llm.base import BaseLLMProvider, LLMRequest, LLMResponse

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider(BaseLLMProvider):
    """Deterministic fake provider for automated testing.

    Configurable to return valid structured responses, malformed JSON,
    arbitrary raw strings, simulated errors (timeouts, rate limits, 500s),
    or a sequence of responses to test retry mechanisms.
    """

    def __init__(
        self,
        default_response: Any = None,
        should_raise: Exception | None = None,
        simulated_latency: float = 0.0,
        response_sequence: list[Any] | None = None,
        model_name: str = "mock-model-v1",
    ) -> None:
        self.default_response = default_response
        self.should_raise = should_raise
        self.simulated_latency = simulated_latency
        self.response_sequence: list[Any] = (
            list(response_sequence) if response_sequence else []
        )
        self.model_name = model_name

        # Introspection attributes for test assertions
        self.call_count: int = 0
        self.recorded_requests: list[LLMRequest] = []

    def reset(self) -> None:
        """Reset call counters and recorded requests."""
        self.call_count = 0
        self.recorded_requests.clear()

    async def _handle_latency_and_exceptions(self) -> None:
        """Simulate execution latency or configured exceptions."""
        if self.simulated_latency > 0:
            await asyncio.sleep(self.simulated_latency)

        if self.should_raise is not None:
            raise self.should_raise

    def _next_response(self) -> Any:
        """Fetch the next response from the sequence, or fall back to default_response."""
        if self.response_sequence:
            return self.response_sequence.pop(0)
        return self.default_response

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate text response from mock configuration."""
        self.call_count += 1
        self.recorded_requests.append(request)

        await self._handle_latency_and_exceptions()

        response_item = self._next_response()

        if isinstance(response_item, Exception):
            raise response_item

        if isinstance(response_item, BaseModel):
            content = response_item.model_dump_json()
        elif isinstance(response_item, dict):
            content = json.dumps(response_item)
        elif isinstance(response_item, str):
            content = response_item
        elif response_item is None:
            content = "{}"
        else:
            content = str(response_item)

        return LLMResponse(
            content=content,
            structured_output=None,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
            total_tokens=len(request.prompt.split()) + len(content.split()),
            latency_seconds=self.simulated_latency,
            model_name=self.model_name,
        )

    async def generate_structured(
        self, request: LLMRequest, schema: type[T]
    ) -> tuple[T, LLMResponse]:
        """Generate structured response, parsing and validating against schema T."""
        self.call_count += 1
        self.recorded_requests.append(request)

        await self._handle_latency_and_exceptions()

        response_item = self._next_response()

        if isinstance(response_item, Exception):
            raise response_item

        # 1. If already an instance of the target schema
        if isinstance(response_item, schema):
            raw_content = response_item.model_dump_json()
            llm_resp = LLMResponse(
                content=raw_content,
                structured_output=response_item,
                prompt_tokens=len(request.prompt.split()),
                completion_tokens=len(raw_content.split()),
                total_tokens=len(request.prompt.split()) + len(raw_content.split()),
                latency_seconds=self.simulated_latency,
                model_name=self.model_name,
            )
            return response_item, llm_resp

        # 1a. If None, attempt validating an empty dictionary
        if response_item is None:
            try:
                validated = schema.model_validate({})
                raw_content = "{}"
                llm_resp = LLMResponse(
                    content=raw_content,
                    structured_output=validated,
                    prompt_tokens=len(request.prompt.split()),
                    completion_tokens=len(raw_content.split()),
                    total_tokens=len(request.prompt.split()) + len(raw_content.split()),
                    latency_seconds=self.simulated_latency,
                    model_name=self.model_name,
                )
                return validated, llm_resp
            except ValidationError:
                pass

        # 1b. If a list of findings provided for a container schema
        if isinstance(response_item, list):
            try:
                wrapped_dict = {"findings": response_item}
                validated = schema.model_validate(wrapped_dict)
                raw_content = json.dumps(
                    [
                        item.model_dump(by_alias=True)
                        if isinstance(item, BaseModel)
                        else item
                        for item in response_item
                    ],
                    default=str,
                )
                llm_resp = LLMResponse(
                    content=raw_content,
                    structured_output=validated,
                    prompt_tokens=len(request.prompt.split()),
                    completion_tokens=len(raw_content.split()),
                    total_tokens=len(request.prompt.split()) + len(raw_content.split()),
                    latency_seconds=self.simulated_latency,
                    model_name=self.model_name,
                )
                return validated, llm_resp
            except ValidationError:
                pass

        # 2. If a dictionary matching the schema
        if isinstance(response_item, dict):
            try:
                validated = schema.model_validate(response_item)
                raw_content = json.dumps(response_item)
                llm_resp = LLMResponse(
                    content=raw_content,
                    structured_output=validated,
                    prompt_tokens=len(request.prompt.split()),
                    completion_tokens=len(raw_content.split()),
                    total_tokens=len(request.prompt.split()) + len(raw_content.split()),
                    latency_seconds=self.simulated_latency,
                    model_name=self.model_name,
                )
                return validated, llm_resp
            except ValidationError as exc:
                raise InvalidPlannerOutputError(
                    message=f"Mock response failed validation against {schema.__name__}: {exc}",
                    raw_output=json.dumps(response_item),
                    validation_errors=exc.errors(),  # type: ignore[arg-type]
                ) from exc

        # 3. If a JSON string or raw text
        if isinstance(response_item, str):
            try:
                parsed_json = json.loads(response_item)
                if not isinstance(parsed_json, dict):
                    raise InvalidPlannerOutputError(
                        message=f"Mock response JSON must be an object/dict, got {type(parsed_json).__name__}",
                        raw_output=response_item,
                    )
                validated = schema.model_validate(parsed_json)
                llm_resp = LLMResponse(
                    content=response_item,
                    structured_output=validated,
                    prompt_tokens=len(request.prompt.split()),
                    completion_tokens=len(response_item.split()),
                    total_tokens=len(request.prompt.split())
                    + len(response_item.split()),
                    latency_seconds=self.simulated_latency,
                    model_name=self.model_name,
                )
                return validated, llm_resp
            except json.JSONDecodeError as exc:
                raise InvalidPlannerOutputError(
                    message=f"Mock response returned malformed non-JSON string: {exc}",
                    raw_output=response_item,
                ) from exc
            except ValidationError as exc:
                raise InvalidPlannerOutputError(
                    message=f"Mock response failed validation against {schema.__name__}: {exc}",
                    raw_output=response_item,
                    validation_errors=exc.errors(),  # type: ignore[arg-type]
                ) from exc

        raise InvalidPlannerOutputError(
            message=f"Unsupported mock response type: {type(response_item).__name__}",
            raw_output=str(response_item),
        )
