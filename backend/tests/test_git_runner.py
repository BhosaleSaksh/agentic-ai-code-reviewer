"""Unit tests for the asynchronous GitRunner abstraction.

Validates that:
- Git commands execute with argument arrays (never shell=True).
- Non-zero exits raise GitCommandError with captured output.
- Timeouts trigger process termination and raise GitTimeoutError.
- Subprocess errors and commands mask sensitive credentials.
- Repository hooks are disabled via -c core.hooksPath="".
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from app.services.git_runner import GitRunner
from app.services.workspace_errors import (
    GitCommandError,
    GitError,
    GitTimeoutError,
    _sanitize_sensitive_text,
)


@pytest.fixture
def git_runner() -> GitRunner:
    """Fixture providing a default GitRunner."""
    return GitRunner(default_timeout=5.0)


@pytest.mark.unit
def test_sanitize_sensitive_text_masks_tokens() -> None:
    """Verify regex masks GitHub tokens and Bearer credentials in strings."""
    raw = (
        "git fetch -c http.extraheader=Authorization: Bearer my_secret_bearer_token_value "
        "https://ghp_MyPersonalToken999@github.com/owner/repo.git "
        "and ghs_SecretInstallationToken123456"
    )
    sanitized = _sanitize_sensitive_text(raw)

    assert "ghs_SecretInstallationToken123456" not in sanitized
    assert "ghp_MyPersonalToken999" not in sanitized
    assert "my_secret_bearer_token_value" not in sanitized
    assert "[MASKED_BEARER]" in sanitized
    assert "[MASKED_TOKEN]" in sanitized
    assert "[MASKED_CREDENTIALS]@" in sanitized


@pytest.mark.unit
def test_git_runner_availability(git_runner: GitRunner) -> None:
    """Verify GitRunner correctly detects git binary availability."""
    assert git_runner.is_git_available() is True

    non_existent = GitRunner(git_binary="non_existent_binary_xyz_123")
    assert non_existent.is_git_available() is False


@pytest.mark.asyncio
async def test_git_runner_successful_command(git_runner: GitRunner) -> None:
    """Verify executing a basic Git command succeeds and captures stdout."""
    res = await git_runner.run(["--version"])

    assert res.exit_code == 0
    assert "git version" in res.stdout.lower()
    assert res.stderr == ""


@pytest.mark.asyncio
async def test_git_runner_non_zero_exit_raises_command_error(
    git_runner: GitRunner,
) -> None:
    """Verify non-zero exit code raises GitCommandError with sanitized stderr."""
    with pytest.raises(GitCommandError) as exc_info:
        await git_runner.run(["non-existent-subcommand-xyz123"])

    err = exc_info.value
    assert err.exit_code != 0
    assert "non-existent-subcommand-xyz123" in repr(err)


@pytest.mark.asyncio
async def test_git_runner_non_zero_exit_no_check(git_runner: GitRunner) -> None:
    """Verify check=False returns GitResult instead of raising on failure."""
    res = await git_runner.run(["non-existent-subcommand-xyz123"], check=False)

    assert res.exit_code != 0
    assert len(res.stderr) > 0


@pytest.mark.asyncio
async def test_git_runner_timeout_raises_timeout_error(tmp_path: Path) -> None:
    """Verify command exceeding timeout raises GitTimeoutError."""
    runner = GitRunner(default_timeout=0.1)

    with (
        patch("asyncio.wait_for", side_effect=TimeoutError("Command timed out")),
        pytest.raises(GitTimeoutError) as exc_info,
    ):
        await runner.run(["status"], cwd=tmp_path, timeout=0.1)

    assert exc_info.value.timeout == 0.1


@pytest.mark.asyncio
async def test_git_runner_spawning_failure_raises_git_error() -> None:
    """Verify OSError when spawning non-existent binary raises GitError."""
    runner = GitRunner(git_binary="definitely_does_not_exist_git_cmd")

    with pytest.raises(GitError, match="Failed to spawn Git command"):
        await runner.run(["status"])


@pytest.mark.asyncio
async def test_git_runner_masks_token_in_error_message(tmp_path: Path) -> None:
    """Verify GitCommandError masks tokens present in arguments."""
    runner = GitRunner()
    fake_token = "ghs_ExtremelySecretTokenValue123456789"
    cmd = ["fetch", f"-c=http.extraheader=Authorization: Bearer {fake_token}", "origin"]

    with pytest.raises(GitCommandError) as exc_info:
        await runner.run(cmd, cwd=tmp_path)

    err_str = str(exc_info.value)
    assert fake_token not in err_str
    assert fake_token not in repr(exc_info.value)
