"""Typed exception taxonomy for the GitHub publication layer.

Classifies publication errors into retryable (rate limit, network, server 5xx)
and non-retryable (authentication, permission, validation, stale commit) failures.
"""

from typing import Any


class PublishError(Exception):
    """Base exception for all GitHub publication failures."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({self.message!r}, retryable={self.retryable})"
        )


class PublishAuthenticationError(PublishError):
    """Raised when GitHub App authentication or token generation fails (non-retryable)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class PublishPermissionError(PublishError):
    """Raised when GitHub returns 403 Forbidden without rate limiting (non-retryable)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class PublishValidationError(PublishError):
    """Raised when a finding fails eligibility, structure, or positioning invariants (non-retryable)."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, retryable=False)
        self.details = details or {}


class PublishStaleCommitError(PublishValidationError):
    """Raised when finding commit SHA does not match current PR head SHA (non-retryable)."""

    def __init__(
        self,
        message: str,
        expected_sha: str,
        current_head_sha: str,
    ) -> None:
        super().__init__(
            message,
            details={
                "expected_sha": expected_sha,
                "current_head_sha": current_head_sha,
            },
        )
        self.expected_sha = expected_sha
        self.current_head_sha = current_head_sha


class DuplicatePublicationError(PublishError):
    """Raised when attempting to publish a finding that has already been published."""

    def __init__(self, message: str, idempotency_key: str) -> None:
        super().__init__(message, retryable=False)
        self.idempotency_key = idempotency_key


class PublishRateLimitError(PublishError):
    """Raised when GitHub API rate limit is hit (retryable with backoff)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message, retryable=True)
        self.retry_after = retry_after


class PublishNetworkError(PublishError):
    """Raised on connection timeout or network transport failures (retryable with backoff)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class PublishServerError(PublishError):
    """Raised when GitHub returns a 5xx server-side error (retryable with backoff)."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message, retryable=True)
        self.status_code = status_code
