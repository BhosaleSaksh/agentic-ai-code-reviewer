"""Workspace and Git operation error definitions.

Defines the typed exception hierarchy for workspace isolation, path validation,
commit SHA consistency verification, disk-space limits, and Git execution errors.
All exceptions ensure sensitive tokens or authorization credentials are never leaked.
"""

from __future__ import annotations

import re


def _sanitize_sensitive_text(text: str | None) -> str:
    """Mask any GitHub tokens, Bearer authorization credentials, or embedded URL passwords."""
    if not text:
        return ""
    # Mask GitHub tokens (ghs_..., ghp_..., gho_..., etc.)
    sanitized = re.sub(r"gh[spoaurs]_[A-Za-z0-9_]{10,}", "[MASKED_TOKEN]", text)
    # Mask Bearer tokens
    sanitized = re.sub(
        r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}",
        r"\1[MASKED_BEARER]",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Mask basic auth in URLs (e.g. https://token@github.com -> https://[MASKED]@github.com)
    sanitized = re.sub(
        r"https?://([^/:]+:[^/@]+@)", "https://[MASKED_CREDENTIALS]@", sanitized
    )
    sanitized = re.sub(
        r"https?://([^/@]+@)", "https://[MASKED_CREDENTIALS]@", sanitized
    )
    return sanitized


class WorkspaceError(Exception):
    """Base exception for all workspace management and Git checkout failures."""

    def __init__(self, message: str) -> None:
        super().__init__(_sanitize_sensitive_text(message))


class WorkspacePathTraversalError(WorkspaceError):
    """Raised when an attempt to escape the workspace root is detected."""


class WorkspaceCommitMismatchError(WorkspaceError):
    """Raised when the actual HEAD commit in the workspace differs from the expected head SHA."""

    def __init__(self, message: str, expected_sha: str, actual_sha: str) -> None:
        super().__init__(message)
        self.expected_sha = expected_sha
        self.actual_sha = actual_sha

    def __repr__(self) -> str:
        return (
            f"WorkspaceCommitMismatchError(expected_sha={self.expected_sha!r}, "
            f"actual_sha={self.actual_sha!r})"
        )


class WorkspaceDiskSpaceError(WorkspaceError):
    """Raised when available disk space is below the required safety threshold."""

    def __init__(self, message: str, available_bytes: int, required_bytes: int) -> None:
        super().__init__(message)
        self.available_bytes = available_bytes
        self.required_bytes = required_bytes


class WorkspaceSizeLimitError(WorkspaceError):
    """Raised when the checked-out workspace exceeds the maximum allowed byte limit."""

    def __init__(self, message: str, actual_bytes: int, limit_bytes: int) -> None:
        super().__init__(message)
        self.actual_bytes = actual_bytes
        self.limit_bytes = limit_bytes


class GitError(WorkspaceError):
    """Base exception for Git subprocess execution failures."""


class GitCommandError(GitError):
    """Raised when a Git command terminates with a non-zero exit status."""

    def __init__(
        self,
        message: str,
        command: list[str],
        exit_code: int,
        stderr: str = "",
        stdout: str = "",
    ) -> None:
        sanitized_msg = _sanitize_sensitive_text(message)
        super().__init__(sanitized_msg)
        # Sanitize command arguments to ensure no tokens leak if passed via args
        self.command = [_sanitize_sensitive_text(arg) for arg in command]
        self.exit_code = exit_code
        self.stderr = _sanitize_sensitive_text(stderr)
        self.stdout = _sanitize_sensitive_text(stdout)

    def __repr__(self) -> str:
        return (
            f"GitCommandError(exit_code={self.exit_code}, "
            f"command={self.command!r}, stderr={self.stderr!r})"
        )


class GitTimeoutError(GitError):
    """Raised when a Git subprocess exceeds its execution timeout."""

    def __init__(self, message: str, command: list[str], timeout: float) -> None:
        sanitized_msg = _sanitize_sensitive_text(message)
        super().__init__(sanitized_msg)
        self.command = [_sanitize_sensitive_text(arg) for arg in command]
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"GitTimeoutError(command={self.command!r}, timeout={self.timeout})"
