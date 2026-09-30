"""Local repository workspace management service.

Creates, verifies, bounds, and cleans up isolated filesystem workspaces for Pull Request review.
Enforces:
- Deterministic, filesystem-safe workspace directory names.
- Strict path traversal prevention.
- Minimum free disk space safety checks.
- Isolated Git checkout with detached HEAD.
- Exact commit SHA consistency verification (actual HEAD == expected head_sha).
- Ephemeral authentication credentials that are never written to Git config, remotes, or disk.
- Maximum workspace byte limits to prevent DoS.
- Reliable async context-manager lifecycle with automated cleanup.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.github.auth import GitHubAppAuthenticator
from app.schemas.workspace import WorkspaceContext
from app.services.git_runner import GitRunner
from app.services.workspace_errors import (
    WorkspaceCommitMismatchError,
    WorkspaceDiskSpaceError,
    WorkspaceError,
    WorkspacePathTraversalError,
    WorkspaceSizeLimitError,
)

logger = logging.getLogger(__name__)

# Strict hex pattern for 40-character Git commit SHAs
_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")


def _remove_readonly(func: Any, path: str, _exc_info: Any) -> None:
    """Error handler for shutil.rmtree to remove read-only attribute on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError as exc:
        logger.debug("Retry removing %s failed: %s", path, exc)


def _calculate_directory_size(path: Path) -> int:
    """Calculate total byte size of all files in a directory."""
    total = 0
    try:
        for root, _, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    # Use lstat to avoid following symlinks outside workspace
                    stat_res = os.lstat(file_path)
                    total += stat_res.st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


class WorkspaceManager:
    """Manages isolated local repository workspaces for code review."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        git_runner: GitRunner | None = None,
        authenticator: GitHubAppAuthenticator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.workspace_root = (
            workspace_root or self.settings.REVIEW_WORKSPACE_ROOT
        ).resolve()
        self.git = git_runner or GitRunner(
            default_timeout=getattr(
                self.settings, "WORKSPACE_COMMAND_TIMEOUT_SECONDS", 60.0
            )
        )
        self.authenticator = authenticator

    def is_configured(self) -> bool:
        """Check whether workspace management is enabled and Git is available."""
        return bool(self.settings.WORKSPACE_ENABLED and self.git.is_git_available())

    def resolve_workspace_path(
        self,
        repository_id: int,
        pr_number: int,
        head_sha: str,
    ) -> Path:
        """Construct a validated, deterministic, isolated path for the review workspace.

        Args:
            repository_id: Integer repository identifier.
            pr_number: Integer pull request number.
            head_sha: 40-character commit SHA.

        Returns:
            Path: Canonical absolute path inside the configured workspace root.

        Raises:
            WorkspacePathTraversalError: If any parameter attempts path traversal or is invalid.
        """
        if not isinstance(repository_id, int) or repository_id <= 0:
            raise WorkspacePathTraversalError(
                f"Invalid repository_id: must be a positive integer, got {repository_id!r}"
            )
        if not isinstance(pr_number, int) or pr_number <= 0:
            raise WorkspacePathTraversalError(
                f"Invalid pr_number: must be a positive integer, got {pr_number!r}"
            )
        if not isinstance(head_sha, str) or not _SHA_REGEX.match(head_sha):
            raise WorkspacePathTraversalError(
                f"Invalid head_sha: must be a 40-character hex string, got {head_sha!r}"
            )

        # Check for traversal indicators in string representation
        normalized_sha = head_sha.lower()
        subpath = Path(str(repository_id)) / f"pr_{pr_number}" / normalized_sha

        target_path = (self.workspace_root / subpath).resolve()

        # Strict containment verification
        if not target_path.is_relative_to(self.workspace_root):
            raise WorkspacePathTraversalError(
                f"Path traversal detected: {target_path} escapes workspace root {self.workspace_root}"
            )

        return target_path

    def check_disk_space(self) -> None:
        """Verify that the filesystem containing workspace_root has sufficient free space.

        Raises:
            WorkspaceDiskSpaceError: If available bytes are below WORKSPACE_MIN_DISK_FREE_BYTES.
        """
        check_dir = self.workspace_root
        while not check_dir.exists() and check_dir.parent != check_dir:
            check_dir = check_dir.parent

        try:
            total, used, free = shutil.disk_usage(check_dir)
        except OSError as exc:
            logger.warning("Could not determine disk usage for %s: %s", check_dir, exc)
            return

        min_required = getattr(
            self.settings, "WORKSPACE_MIN_DISK_FREE_BYTES", 1024 * 1024 * 1024
        )
        if free < min_required:
            raise WorkspaceDiskSpaceError(
                message=(
                    f"Insufficient disk space for review workspace on {check_dir}: "
                    f"available {free} bytes, required {min_required} bytes"
                ),
                available_bytes=free,
                required_bytes=min_required,
            )

    async def cleanup_workspace(self, workspace_path: Path) -> bool:
        """Safely remove a workspace directory.

        Args:
            workspace_path: Path to the workspace directory to remove.

        Returns:
            bool: True if cleanup succeeded or directory did not exist, False otherwise.
        """
        # Ensure path is within workspace_root before deleting anything
        resolved = workspace_path.resolve()
        if not resolved.is_relative_to(self.workspace_root):
            logger.error(
                "Refusing to clean up path outside workspace root: %s", resolved
            )
            return False

        if not resolved.exists():
            return True

        logger.debug("Cleaning up workspace directory: %s", resolved)
        try:
            shutil.rmtree(resolved, onerror=_remove_readonly)
            return True
        except Exception as exc:
            logger.error("Failed to remove workspace directory %s: %s", resolved, exc)
            return False

    async def create_workspace(
        self,
        repository_id: int,
        repository_full_name: str,
        pr_number: int,
        head_sha: str,
        base_sha: str | None = None,
        installation_id: int | None = None,
        source_repo_url: str | None = None,
        auth_token: SecretStr | None = None,
    ) -> WorkspaceContext:
        """Create an isolated workspace and checkout the exact expected commit.

        Args:
            repository_id: Repository ID.
            repository_full_name: Target repository owner/name.
            pr_number: Pull request number.
            head_sha: Expected 40-character commit SHA.
            base_sha: Optional base commit SHA.
            installation_id: Optional GitHub App installation ID.
            source_repo_url: Optional Git clone/fetch URL (defaults to GitHub HTTPS URL).
            auth_token: Optional ephemeral installation token for authentication.

        Returns:
            WorkspaceContext: Strongly typed representation of verified workspace.

        Raises:
            WorkspaceError: If path resolution, disk space, Git execution, or SHA validation fails.
        """
        # 1. Path safety and containment
        workspace_path = self.resolve_workspace_path(repository_id, pr_number, head_sha)

        # 2. Check disk space threshold
        self.check_disk_space()

        # 3. Clean up any existing directory to ensure total isolation
        if workspace_path.exists():
            await self.cleanup_workspace(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)

        workspace_id = f"ws-{repository_id}-pr{pr_number}-{head_sha[:12]}"
        logger.info(
            "Creating workspace %s at %s for %s PR #%d (expected SHA=%s)",
            workspace_id,
            workspace_path,
            repository_full_name,
            pr_number,
            head_sha,
        )

        # 4. Resolve source remote URL
        remote_url = source_repo_url
        if not remote_url:
            base_url = getattr(
                self.settings, "GITHUB_API_BASE_URL", "https://api.github.com"
            )
            # For standard github.com, remote is https://github.com/{owner}/{repo}.git
            if "api.github.com" in base_url:
                remote_url = f"https://github.com/{repository_full_name}.git"
            else:
                # Custom/enterprise URL support
                host = (
                    base_url.replace("https://", "")
                    .replace("http://", "")
                    .split("/")[0]
                )
                remote_url = f"https://{host}/{repository_full_name}.git"

        # 5. Resolve ephemeral authentication token
        token_str: str | None = None
        if auth_token:
            token_str = auth_token.get_secret_value()
        elif self.authenticator and installation_id:
            token_obj = await self.authenticator.get_installation_token(installation_id)
            token_str = token_obj.token.get_secret_value()
        elif self.authenticator and self.settings.GITHUB_APP_INSTALLATION_ID:
            token_obj = await self.authenticator.get_installation_token(
                self.settings.GITHUB_APP_INSTALLATION_ID
            )
            token_str = token_obj.token.get_secret_value()

        # 6. Execute Git checkout flow
        try:
            # 6a. Initialize repository
            await self.git.run(["init"], cwd=workspace_path)

            # 6b. Add remote (NEVER embed credentials in remote URL)
            await self.git.run(
                ["remote", "add", "origin", remote_url], cwd=workspace_path
            )

            # 6c. Fetch target commit using ephemeral header
            fetch_extra_args: list[str] = []
            if token_str and remote_url.startswith("http"):
                fetch_extra_args = [
                    "-c",
                    f"http.extraheader=Authorization: Bearer {token_str}",
                ]

            # Attempt shallow fetch of exact commit first
            fetched = False
            try:
                await self.git.run(
                    fetch_extra_args + ["fetch", "--depth", "1", "origin", head_sha],
                    cwd=workspace_path,
                )
                fetched = True
            except Exception as exc:
                logger.debug(
                    "Shallow fetch of SHA %s failed, falling back to PR ref: %s",
                    head_sha,
                    exc,
                )

            # Fallback to PR head ref if direct SHA fetch is not advertised
            if not fetched:
                try:
                    await self.git.run(
                        fetch_extra_args
                        + ["fetch", "origin", f"pull/{pr_number}/head"],
                        cwd=workspace_path,
                    )
                    fetched = True
                except Exception:
                    # Final fallback: fetch origin without refspec if local repo or branch
                    await self.git.run(
                        fetch_extra_args + ["fetch", "origin", head_sha],
                        cwd=workspace_path,
                    )

            # 6d. Detached checkout of the expected commit
            await self.git.run(["checkout", "--detach", head_sha], cwd=workspace_path)

            # 7. Exact SHA Verification
            res_head = await self.git.run(["rev-parse", "HEAD"], cwd=workspace_path)
            actual_head = res_head.stdout.strip()

            if actual_head.lower() != head_sha.lower():
                raise WorkspaceCommitMismatchError(
                    message=(
                        f"Commit verification failed for {repository_full_name}: "
                        f"expected {head_sha}, but HEAD is at {actual_head}"
                    ),
                    expected_sha=head_sha,
                    actual_sha=actual_head,
                )

            # 8. Detached HEAD verification
            res_symbolic = await self.git.run(
                ["symbolic-ref", "-q", "HEAD"], cwd=workspace_path, check=False
            )
            is_detached = res_symbolic.exit_code != 0

            # 9. Security Audit: verify no credentials remain in .git/config
            git_config_path = workspace_path / ".git" / "config"
            if git_config_path.exists():
                config_content = git_config_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                if token_str and token_str in config_content:
                    raise WorkspaceError(
                        "Security violation: ephemeral token was persisted into .git/config"
                    )
                if "@" in config_content and "https://" in config_content:
                    # Verify no http://user:pass@ style remote was written
                    match = re.search(r"https?://[^/]+@", config_content)
                    if match:
                        raise WorkspaceError(
                            "Security violation: remote credentials found in .git/config"
                        )

            # 10. Workspace Size Verification
            size_bytes = _calculate_directory_size(workspace_path)
            max_size = getattr(
                self.settings, "WORKSPACE_MAX_SIZE_BYTES", 500 * 1024 * 1024
            )
            if size_bytes > max_size:
                raise WorkspaceSizeLimitError(
                    message=(
                        f"Workspace for {repository_full_name} exceeds maximum byte limit: "
                        f"actual {size_bytes} bytes, limit {max_size} bytes"
                    ),
                    actual_bytes=size_bytes,
                    limit_bytes=max_size,
                )

            context = WorkspaceContext(
                workspace_id=workspace_id,
                workspace_path=workspace_path,
                repository_id=repository_id,
                repository_full_name=repository_full_name,
                pr_number=pr_number,
                expected_head_sha=head_sha,
                actual_head_sha=actual_head,
                base_sha=base_sha,
                size_bytes=size_bytes,
                is_detached_head=is_detached,
            )

            logger.info(
                "Workspace %s successfully prepared at %s (SHA=%s, size=%d bytes, detached=%s)",
                workspace_id,
                workspace_path,
                actual_head,
                size_bytes,
                is_detached,
            )
            return context

        except Exception as exc:
            logger.error("Failed to prepare workspace %s: %s", workspace_id, exc)
            # Ensure failed partial workspace is removed
            await self.cleanup_workspace(workspace_path)
            raise

    @asynccontextmanager
    async def prepare(
        self,
        repository_id: int,
        repository_full_name: str,
        pr_number: int,
        head_sha: str,
        base_sha: str | None = None,
        installation_id: int | None = None,
        source_repo_url: str | None = None,
        auth_token: SecretStr | None = None,
    ) -> AsyncIterator[WorkspaceContext]:
        """Asynchronous context manager managing workspace preparation and guaranteed cleanup.

        Usage:
            async with workspace_manager.prepare(...) as workspace:
                # Execute analyzers / static checks in workspace.workspace_path
                ...
            # Workspace is automatically removed on context exit
        """
        workspace_path = self.resolve_workspace_path(repository_id, pr_number, head_sha)
        context: WorkspaceContext | None = None
        has_error = False

        try:
            context = await self.create_workspace(
                repository_id=repository_id,
                repository_full_name=repository_full_name,
                pr_number=pr_number,
                head_sha=head_sha,
                base_sha=base_sha,
                installation_id=installation_id,
                source_repo_url=source_repo_url,
                auth_token=auth_token,
            )
            yield context
        except Exception:
            has_error = True
            if getattr(self.settings, "WORKSPACE_RETENTION_ON_FAILURE", False):
                logger.warning(
                    "Retaining failed workspace for debugging (WORKSPACE_RETENTION_ON_FAILURE=True): %s",
                    workspace_path,
                )
            else:
                await self.cleanup_workspace(workspace_path)
            raise
        finally:
            if not has_error:
                await self.cleanup_workspace(workspace_path)
