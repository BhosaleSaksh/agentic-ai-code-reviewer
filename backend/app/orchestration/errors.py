"""Workflow-level error categories and exception hierarchy for LangGraph review orchestration.

Defines explicit, typed error classifications distinguishing retryable transient errors
from deterministic validation failures per Section K of the project architecture.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class WorkflowErrorCategory(StrEnum):
    """Categorization of workflow failures for telemetry, metrics, and retry handling."""

    INVALID_PLANNER_OUTPUT = "INVALID_PLANNER_OUTPUT"
    INVALID_SPECIALIST_OUTPUT = "INVALID_SPECIALIST_OUTPUT"
    INVALID_CRITIC_OUTPUT = "INVALID_CRITIC_OUTPUT"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    CONTEXT_PREPARATION_FAILURE = "CONTEXT_PREPARATION_FAILURE"
    EVIDENCE_VALIDATION_FAILURE = "EVIDENCE_VALIDATION_FAILURE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    WORKFLOW_EXECUTION_FAILURE = "WORKFLOW_EXECUTION_FAILURE"


class WorkflowError(Exception):
    """Base exception for all review workflow and orchestration errors."""

    def __init__(
        self,
        message: str,
        category: WorkflowErrorCategory = WorkflowErrorCategory.WORKFLOW_EXECUTION_FAILURE,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        """Serialize error metadata for audit logging and state recording."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "category": self.category.value,
            "retryable": self.retryable,
            "details": self.details,
        }


class InvalidPlannerOutputError(WorkflowError):
    """Raised when the Planner Agent outputs malformed JSON or violates ReviewPlan schema."""

    def __init__(
        self,
        message: str,
        raw_output: str | None = None,
        validation_errors: list[dict[str, object]] | None = None,
    ) -> None:
        details: dict[str, object] = {}
        if raw_output is not None:
            details["raw_output"] = raw_output[:1000]  # bounded preview
        if validation_errors:
            details["validation_errors"] = validation_errors

        super().__init__(
            message=message,
            category=WorkflowErrorCategory.INVALID_PLANNER_OUTPUT,
            retryable=False,
            details=details,
        )


class InvalidSpecialistOutputError(WorkflowError):
    """Raised when a Specialist Agent outputs malformed JSON or violates finding schema."""

    def __init__(
        self,
        message: str,
        agent_name: str = "unknown",
        raw_output: str | None = None,
        validation_errors: list[dict[str, object]] | None = None,
    ) -> None:
        details: dict[str, object] = {"agent_name": agent_name}
        if raw_output is not None:
            details["raw_output"] = raw_output[:1000]
        if validation_errors:
            details["validation_errors"] = validation_errors

        super().__init__(
            message=message,
            category=WorkflowErrorCategory.INVALID_SPECIALIST_OUTPUT,
            retryable=False,
            details=details,
        )


class InvalidCriticOutputError(WorkflowError):
    """Raised when the Critic Agent outputs malformed JSON or violates verification schema."""

    def __init__(
        self,
        message: str,
        finding_id: str | None = None,
        raw_output: str | None = None,
        validation_errors: list[Any] | None = None,
    ) -> None:
        details: dict[str, object] = {}
        if finding_id:
            details["finding_id"] = finding_id
        if raw_output is not None:
            details["raw_output"] = raw_output[:1000]
        if validation_errors:
            details["validation_errors"] = validation_errors

        super().__init__(
            message=message,
            category=WorkflowErrorCategory.INVALID_CRITIC_OUTPUT,
            retryable=False,
            details=details,
        )


class LLMProviderError(WorkflowError):
    """Raised when an external LLM provider returns a transient or infrastructure failure."""

    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        details: dict[str, object] = {
            "provider": provider,
            "status_code": status_code,
        }
        super().__init__(
            message=message,
            category=WorkflowErrorCategory.LLM_PROVIDER_ERROR,
            retryable=retryable,
            details=details,
        )


class LLMTimeoutError(WorkflowError):
    """Raised when an LLM provider call exceeds the configured timeout threshold."""

    def __init__(
        self,
        message: str,
        timeout_seconds: float,
        provider: str = "unknown",
    ) -> None:
        super().__init__(
            message=message,
            category=WorkflowErrorCategory.LLM_TIMEOUT,
            retryable=True,
            details={"timeout_seconds": timeout_seconds, "provider": provider},
        )


class ContextPreparationError(WorkflowError):
    """Raised when PR diff or static evidence cannot be bounded or formatted."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(
            message=message,
            category=WorkflowErrorCategory.CONTEXT_PREPARATION_FAILURE,
            retryable=False,
            details=details,
        )


class EvidenceValidationError(WorkflowError):
    """Raised when evidence items fail provenance or commit SHA validation."""

    def __init__(
        self,
        message: str,
        expected_commit_sha: str,
        actual_commit_sha: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            category=WorkflowErrorCategory.EVIDENCE_VALIDATION_FAILURE,
            retryable=False,
            details={
                "expected_commit_sha": expected_commit_sha,
                "actual_commit_sha": actual_commit_sha,
            },
        )


class WorkflowConfigurationError(WorkflowError):
    """Raised when review graph configuration or credentials are missing or invalid."""

    def __init__(self, message: str, parameter: str | None = None) -> None:
        super().__init__(
            message=message,
            category=WorkflowErrorCategory.CONFIGURATION_ERROR,
            retryable=False,
            details={"parameter": parameter} if parameter else {},
        )


def is_retryable_error(exc: BaseException) -> bool:
    """Determine whether an error is transient and safe for exponential backoff retry."""
    if isinstance(exc, WorkflowError):
        return exc.retryable
    return False
