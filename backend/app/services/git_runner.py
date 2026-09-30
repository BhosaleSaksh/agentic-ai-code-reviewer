"""Asynchronous Git command execution abstraction.

Provides secure, structured subprocess execution for Git commands.
Guarantees:
- Subprocess execution uses argument arrays only (never shell=True).
- Git repository hooks are explicitly disabled via -c core.hooksPath="".
- Terminal prompts are disabled via GIT_TERMINAL_PROMPT=0.
- Timeouts are strictly enforced; hung processes are killed.
- All command arguments, stdout, stderr, and log output are sanitized to prevent credential leakage.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.services.workspace_errors import (
    GitCommandError,
    GitError,
    GitTimeoutError,
    _sanitize_sensitive_text,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitResult:
    """Structured result of a Git command execution."""

    stdout: str
    stderr: str
    exit_code: int


class GitRunner:
    """Asynchronous runner for isolated Git commands."""

    def __init__(
        self,
        git_binary: str | None = None,
        default_timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self.git_binary = git_binary or shutil.which("git") or "git"
        self.default_timeout = (
            default_timeout
            if default_timeout is not None
            else getattr(settings, "WORKSPACE_COMMAND_TIMEOUT_SECONDS", 60.0)
        )

    def is_git_available(self) -> bool:
        """Check if Git binary is present and executable on the host system."""
        return shutil.which(self.git_binary) is not None

    async def run(
        self,
        args: list[str],
        cwd: Path | str | None = None,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        check: bool = True,
    ) -> GitResult:
        """Execute a Git command with structured arguments and strict timeout.

        Args:
            args: Git subcommands and arguments (e.g. ['checkout', '--detach', 'SHA']).
            cwd: Working directory for Git command execution.
            timeout: Command timeout in seconds.
            extra_env: Additional environment variables for the subprocess.
            check: If True, raises GitCommandError on non-zero exit code.

        Returns:
            GitResult: Structured stdout, stderr, and exit code.

        Raises:
            GitTimeoutError: If execution exceeds the specified timeout.
            GitCommandError: If command exits non-zero and check is True.
            GitError: If the process cannot be spawned.
        """
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # Ensure hooks cannot execute: inject -c core.hooksPath="" before subcommands
        # Also disable credential helper queries and terminal prompts
        full_cmd = [self.git_binary, "-c", "core.hooksPath="] + list(args)

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = ""
        env["GIT_OPTIONAL_LOCKS"] = "0"
        if extra_env:
            env.update(extra_env)

        working_dir = str(cwd) if cwd else None

        sanitized_cmd = [_sanitize_sensitive_text(arg) for arg in full_cmd]
        logger.debug("Executing Git command: %s (cwd=%s)", sanitized_cmd, working_dir)

        try:
            process = await asyncio.create_subprocess_exec(
                full_cmd[0],
                *full_cmd[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env,
            )
        except OSError as exc:
            sanitized_err = _sanitize_sensitive_text(str(exc))
            logger.error("Failed to spawn Git process: %s", sanitized_err)
            raise GitError(
                f"Failed to spawn Git command {sanitized_cmd[0]}: {sanitized_err}"
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=effective_timeout,
            )
        except TimeoutError as exc:
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
            logger.error(
                "Git command timed out after %s seconds: %s",
                effective_timeout,
                sanitized_cmd,
            )
            raise GitTimeoutError(
                message=f"Git command timed out after {effective_timeout}s: {' '.join(sanitized_cmd)}",
                command=sanitized_cmd,
                timeout=effective_timeout,
            ) from exc

        exit_code = process.returncode or 0
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        result = GitResult(stdout=stdout, stderr=stderr, exit_code=exit_code)

        if check and exit_code != 0:
            sanitized_stderr = _sanitize_sensitive_text(stderr)
            logger.error(
                "Git command failed (exit=%d): %s, stderr=%s",
                exit_code,
                sanitized_cmd,
                sanitized_stderr,
            )
            raise GitCommandError(
                message=f"Git command failed with exit code {exit_code}: {sanitized_stderr}",
                command=sanitized_cmd,
                exit_code=exit_code,
                stderr=sanitized_stderr,
                stdout=_sanitize_sensitive_text(stdout),
            )

        return result
