"""GitHub integration domain exception hierarchy.

Provides explicit typed exceptions for GitHub App authentication, REST API interactions,
rate limiting, and PR context extraction without leaking sensitive credentials into logs.
"""

from datetime import datetime
from typing import Any


class GitHubError(Exception):
    """Base exception for all GitHub integration failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r})"


class GitHubConfigurationError(GitHubError):
    """Raised when GitHub App settings, private keys, or installation IDs are invalid."""


class GitHubAuthenticationError(GitHubError):
    """Raised when GitHub App JWT creation or authentication fails (HTTP 401)."""


class GitHubPermissionError(GitHubError):
    """Raised when GitHub returns HTTP 403 Forbidden (insufficient App permissions)."""


class GitHubNotFoundError(GitHubError):
    """Raised when a repository, pull request, or resource is not found (HTTP 404)."""


class GitHubRateLimitError(GitHubError):
    """Raised when GitHub API rate limits are exceeded (HTTP 429 or HTTP 403 rate-limited)."""

    def __init__(
        self,
        message: str,
        limit: int | None = None,
        remaining: int | None = None,
        reset_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at


class GitHubServerError(GitHubError):
    """Raised when GitHub returns a 5xx server-side failure."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubNetworkError(GitHubError):
    """Raised when network transport fails or requests time out."""


class GitHubResponseError(GitHubError):
    """Raised when GitHub returns an unexpected or malformed response envelope."""


class GitHubUnprocessableEntityError(GitHubResponseError):
    """Raised when GitHub returns HTTP 422 Unprocessable Entity (e.g. invalid diff position or comment anchoring failure)."""

    def __init__(
        self,
        message: str,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []


class GitHubCommitMismatchError(GitHubError):
    """Raised when the retrieved PR head SHA does not match the expected commit SHA."""

    def __init__(
        self,
        message: str,
        expected_sha: str,
        retrieved_sha: str,
    ) -> None:
        super().__init__(message)
        self.expected_sha = expected_sha
        self.retrieved_sha = retrieved_sha


class GitHubDiffTooLargeError(GitHubError):
    """Raised when the retrieved PR unified diff exceeds configured safety bounds."""

    def __init__(self, message: str, byte_count: int, max_bytes: int) -> None:
        super().__init__(message)
        self.byte_count = byte_count
        self.max_bytes = max_bytes
