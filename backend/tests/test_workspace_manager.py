"""Unit tests for WorkspaceManager lifecycle, boundaries, and security.

Validates that:
- Workspaces are cleanly created and destroyed.
- Disk space limits prevent execution when storage is low.
- Size limits prevent unbounded repository checkouts.
- Commit SHA mismatches raise WorkspaceCommitMismatchError.
- Context manager cleans up on success and failure.
- Failed workspaces can optionally be retained for debugging.
- Ephemeral tokens are never persisted in .git/config.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.config import Settings
from app.schemas.workspace import WorkspaceContext
from app.services.git_runner import GitResult, GitRunner
from app.services.workspace_errors import (
    WorkspaceCommitMismatchError,
    WorkspaceDiskSpaceError,
    WorkspaceError,
    WorkspaceSizeLimitError,
)
from app.services.workspace_manager import WorkspaceManager
from pydantic import SecretStr


@pytest.fixture
def mock_git_runner() -> MagicMock:
    """Fixture providing a mocked GitRunner."""
    runner = MagicMock(spec=GitRunner)
    runner.is_git_available.return_value = True
    runner.run = AsyncMock(return_value=GitResult(stdout="", stderr="", exit_code=0))
    return runner


@pytest.fixture
def workspace_manager(tmp_path: Path, mock_git_runner: MagicMock) -> WorkspaceManager:
    """Fixture providing WorkspaceManager with temporary root and mock git runner."""
    settings = Settings(
        REVIEW_WORKSPACE_ROOT=tmp_path,
        WORKSPACE_MIN_DISK_FREE_BYTES=1000,
        WORKSPACE_MAX_SIZE_BYTES=10_000_000,
    )
    return WorkspaceManager(
        workspace_root=tmp_path,
        git_runner=mock_git_runner,
        settings=settings,
    )


@pytest.mark.unit
def test_workspace_manager_is_configured(workspace_manager: WorkspaceManager) -> None:
    """Verify is_configured reflects settings and git availability."""
    assert workspace_manager.is_configured() is True

    with patch.object(workspace_manager.git, "is_git_available", return_value=False):
        assert workspace_manager.is_configured() is False


@pytest.mark.asyncio
async def test_cleanup_workspace_idempotent(
    workspace_manager: WorkspaceManager, tmp_path: Path
) -> None:
    """Verify cleanup succeeds cleanly on both existing and non-existent directories."""
    target_dir = tmp_path / "123" / "pr_1" / "sha"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "sample.txt").write_text("hello", encoding="utf-8")

    assert target_dir.exists()
    cleaned = await workspace_manager.cleanup_workspace(target_dir)
    assert cleaned is True
    assert not target_dir.exists()

    # Second cleanup on non-existent directory must succeed idempotently
    cleaned_again = await workspace_manager.cleanup_workspace(target_dir)
    assert cleaned_again is True


@pytest.mark.asyncio
async def test_cleanup_workspace_refuses_outside_root(
    workspace_manager: WorkspaceManager, tmp_path: Path
) -> None:
    """Verify cleanup refuses to delete paths outside the configured workspace root."""
    outside_dir = tmp_path.parent / "unrelated_directory_safe_test"
    outside_dir.mkdir(parents=True, exist_ok=True)
    try:
        cleaned = await workspace_manager.cleanup_workspace(outside_dir)
        assert cleaned is False
        assert outside_dir.exists()
    finally:
        if outside_dir.exists():
            outside_dir.rmdir()


@pytest.mark.unit
def test_check_disk_space_insufficient_raises(
    workspace_manager: WorkspaceManager,
) -> None:
    """Verify WorkspaceDiskSpaceError is raised when available bytes are below threshold."""
    with patch("shutil.disk_usage", return_value=(100_000_000, 99_999_900, 100)):
        with pytest.raises(WorkspaceDiskSpaceError) as exc_info:
            workspace_manager.check_disk_space()

        assert exc_info.value.available_bytes == 100
        assert exc_info.value.required_bytes == 1000


@pytest.mark.asyncio
async def test_create_workspace_success(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify create_workspace orchestrates git commands and returns verified WorkspaceContext."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        if "symbolic-ref" in args:
            # Symbolic-ref returns 1 when HEAD is detached
            return GitResult(stdout="", stderr="", exit_code=1)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    context = await workspace_manager.create_workspace(
        repository_id=1296269,
        repository_full_name="octocat/Hello-World",
        pr_number=42,
        head_sha=target_sha,
        base_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        auth_token=SecretStr("ghs_testToken123"),
    )

    assert isinstance(context, WorkspaceContext)
    assert context.repository_id == 1296269
    assert context.repository_full_name == "octocat/Hello-World"
    assert context.pr_number == 42
    assert context.expected_head_sha == target_sha
    assert context.actual_head_sha == target_sha
    assert context.is_detached_head is True
    assert context.workspace_path.exists()

    # Clean up workspace directory created during test
    await workspace_manager.cleanup_workspace(context.workspace_path)


@pytest.mark.asyncio
async def test_create_workspace_commit_mismatch_raises(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify WorkspaceCommitMismatchError is raised when rev-parse returns unexpected SHA."""
    expected_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    wrong_sha = "1111111111111111111111111111111111111111"

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=wrong_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    with pytest.raises(WorkspaceCommitMismatchError) as exc_info:
        await workspace_manager.create_workspace(
            repository_id=100,
            repository_full_name="org/repo",
            pr_number=1,
            head_sha=expected_sha,
        )

    assert exc_info.value.expected_sha == expected_sha
    assert exc_info.value.actual_sha == wrong_sha


@pytest.mark.asyncio
async def test_create_workspace_size_limit_exceeded(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify WorkspaceSizeLimitError is raised when checked-out workspace exceeds byte limit."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    workspace_manager.settings.WORKSPACE_MAX_SIZE_BYTES = 50

    async def mock_git_run(
        args: list[str], cwd: Path | None = None, **_kwargs: object
    ) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        if "init" in args and cwd:
            # Create a file that exceeds the 50 bytes limit
            (Path(cwd) / "large_file.dat").write_bytes(b"A" * 200)
            return GitResult(stdout="", stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    with pytest.raises(WorkspaceSizeLimitError) as exc_info:
        await workspace_manager.create_workspace(
            repository_id=100,
            repository_full_name="org/repo",
            pr_number=1,
            head_sha=target_sha,
        )

    assert exc_info.value.limit_bytes == 50
    assert exc_info.value.actual_bytes >= 200


@pytest.mark.asyncio
async def test_prepare_context_manager_cleanup_on_success(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify prepare context manager automatically removes workspace on exit."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    workspace_dir: Path | None = None
    async with workspace_manager.prepare(
        repository_id=10,
        repository_full_name="org/repo",
        pr_number=1,
        head_sha=target_sha,
    ) as ws:
        workspace_dir = ws.workspace_path
        assert workspace_dir.exists()

    # After context exit, directory must be removed
    assert workspace_dir is not None
    assert not workspace_dir.exists()


@pytest.mark.asyncio
async def test_prepare_context_manager_cleanup_on_exception(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify prepare context manager cleans up directory when block raises exception."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    workspace_dir: Path | None = None
    with pytest.raises(RuntimeError, match="Simulated analyzer crash"):
        async with workspace_manager.prepare(
            repository_id=10,
            repository_full_name="org/repo",
            pr_number=1,
            head_sha=target_sha,
        ) as ws:
            workspace_dir = ws.workspace_path
            assert workspace_dir.exists()
            raise RuntimeError("Simulated analyzer crash")

    # Directory must be removed even though exception was raised
    assert workspace_dir is not None
    assert not workspace_dir.exists()


@pytest.mark.asyncio
async def test_prepare_retention_on_failure_flag(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify workspace is retained if WORKSPACE_RETENTION_ON_FAILURE=True when exception occurs."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    workspace_manager.settings.WORKSPACE_RETENTION_ON_FAILURE = True

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    workspace_dir: Path | None = None
    try:
        with pytest.raises(RuntimeError, match="Diagnostic test error"):
            async with workspace_manager.prepare(
                repository_id=10,
                repository_full_name="org/repo",
                pr_number=1,
                head_sha=target_sha,
            ) as ws:
                workspace_dir = ws.workspace_path
                raise RuntimeError("Diagnostic test error")

        # Because WORKSPACE_RETENTION_ON_FAILURE is True, directory should be retained
        assert workspace_dir is not None
        assert workspace_dir.exists()
    finally:
        if workspace_dir and workspace_dir.exists():
            await workspace_manager.cleanup_workspace(workspace_dir)


@pytest.mark.unit
def test_workspace_context_validator_mismatch_raises() -> None:
    """Verify WorkspaceContext model validator rejects mismatched head SHAs."""
    with pytest.raises(WorkspaceCommitMismatchError) as exc_info:
        WorkspaceContext(
            workspace_id="ws-1-pr1-test",
            workspace_path=Path("/tmp/ws"),
            repository_id=1,
            repository_full_name="test/repo",
            pr_number=1,
            expected_head_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            actual_head_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )

    assert exc_info.value.expected_sha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert exc_info.value.actual_sha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_create_workspace_with_authenticator(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify create_workspace fetches installation token via authenticator."""
    from app.github.auth import GitHubAppAuthenticator
    from app.schemas.github import GitHubInstallationToken

    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    mock_auth = MagicMock(spec=GitHubAppAuthenticator)
    mock_auth.get_installation_token = AsyncMock(
        return_value=GitHubInstallationToken(
            token=SecretStr("ghs_mockAuthToken12345"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    workspace_manager.authenticator = mock_auth

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    context = await workspace_manager.create_workspace(
        repository_id=999,
        repository_full_name="org/authenticated-repo",
        pr_number=12,
        head_sha=target_sha,
        installation_id=444555,
    )

    mock_auth.get_installation_token.assert_awaited_once_with(444555)
    assert context.actual_head_sha == target_sha
    await workspace_manager.cleanup_workspace(context.workspace_path)


@pytest.mark.asyncio
async def test_create_workspace_fallback_to_settings_installation_id(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify create_workspace uses settings.GITHUB_APP_INSTALLATION_ID if not passed."""
    from app.github.auth import GitHubAppAuthenticator
    from app.schemas.github import GitHubInstallationToken

    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    workspace_manager.settings.GITHUB_APP_INSTALLATION_ID = 888999
    mock_auth = MagicMock(spec=GitHubAppAuthenticator)
    mock_auth.get_installation_token = AsyncMock(
        return_value=GitHubInstallationToken(
            token=SecretStr("ghs_fallbackToken"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    workspace_manager.authenticator = mock_auth

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    context = await workspace_manager.create_workspace(
        repository_id=999,
        repository_full_name="org/fallback-repo",
        pr_number=12,
        head_sha=target_sha,
        installation_id=None,
    )

    mock_auth.get_installation_token.assert_awaited_once_with(888999)
    assert context.actual_head_sha == target_sha
    await workspace_manager.cleanup_workspace(context.workspace_path)


@pytest.mark.asyncio
async def test_create_workspace_custom_enterprise_base_url(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify custom GITHUB_API_BASE_URL resolves enterprise remote URL."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    workspace_manager.settings.GITHUB_API_BASE_URL = (
        "https://github.enterprise.corp/api/v3"
    )

    call_log: list[list[str]] = []

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        call_log.append(args)
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    context = await workspace_manager.create_workspace(
        repository_id=999,
        repository_full_name="mycorp/custom-repo",
        pr_number=1,
        head_sha=target_sha,
    )

    assert any(
        "https://github.enterprise.corp/mycorp/custom-repo.git" in arg
        for cmd in call_log
        for arg in cmd
    )
    await workspace_manager.cleanup_workspace(context.workspace_path)


@pytest.mark.asyncio
async def test_create_workspace_security_violation_token_in_config_raises(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify WorkspaceError is raised if ephemeral token is written into .git/config."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    leak_token = "ghs_leakedTokenValue123"

    async def mock_git_run(
        args: list[str], cwd: Path | None = None, **_kwargs: object
    ) -> GitResult:
        if "init" in args and cwd:
            # Simulate a git config containing the leaked token
            git_dir = Path(cwd) / ".git"
            git_dir.mkdir(parents=True, exist_ok=True)
            (git_dir / "config").write_text(
                f"[core]\n  secret = {leak_token}\n", encoding="utf-8"
            )
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    with pytest.raises(WorkspaceError, match="Security violation: ephemeral token"):
        await workspace_manager.create_workspace(
            repository_id=123,
            repository_full_name="org/leak-test",
            pr_number=1,
            head_sha=target_sha,
            auth_token=SecretStr(leak_token),
        )


@pytest.mark.asyncio
async def test_create_workspace_security_violation_credentials_in_remote_raises(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify WorkspaceError is raised if remote URL contains user:pass credentials in .git/config."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"

    async def mock_git_run(
        args: list[str], cwd: Path | None = None, **_kwargs: object
    ) -> GitResult:
        if "init" in args and cwd:
            git_dir = Path(cwd) / ".git"
            git_dir.mkdir(parents=True, exist_ok=True)
            (git_dir / "config").write_text(
                '[remote "origin"]\n  url = https://user:pass@github.com/org/repo.git\n',
                encoding="utf-8",
            )
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    with pytest.raises(WorkspaceError, match="Security violation: remote credentials"):
        await workspace_manager.create_workspace(
            repository_id=123,
            repository_full_name="org/cred-test",
            pr_number=1,
            head_sha=target_sha,
        )


@pytest.mark.asyncio
async def test_create_workspace_shallow_fetch_fallback_success(
    workspace_manager: WorkspaceManager, mock_git_runner: MagicMock
) -> None:
    """Verify shallow fetch failure falls back to PR head ref fetch."""
    target_sha = "6dcb09b5b57875f334f61aebed695e2e4193db5e"
    call_log: list[list[str]] = []

    async def mock_git_run(args: list[str], **_kwargs: object) -> GitResult:
        call_log.append(args)
        if "--depth" in args:
            raise RuntimeError("Shallow fetch not allowed")
        if "rev-parse" in args:
            return GitResult(stdout=target_sha, stderr="", exit_code=0)
        return GitResult(stdout="", stderr="", exit_code=0)

    mock_git_runner.run = AsyncMock(side_effect=mock_git_run)

    context = await workspace_manager.create_workspace(
        repository_id=123,
        repository_full_name="org/fallback-test",
        pr_number=7,
        head_sha=target_sha,
    )

    assert context.actual_head_sha == target_sha
    # Verify fallback call to pull/7/head was made
    assert any("pull/7/head" in arg for cmd in call_log for arg in cmd)
    await workspace_manager.cleanup_workspace(context.workspace_path)
