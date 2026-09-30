"""GitHub integration service orchestrating PR context retrieval.

Coordinates GitHub App authentication, REST client calls, and deterministic unified
diff parsing to extract strongly typed, verified PullRequestContext models.
"""

import logging

import httpx

from app.context.diff_parser import DiffParser
from app.core.config import get_settings
from app.github.auth import GitHubAppAuthenticator
from app.github.client import GitHubClient
from app.github.errors import (
    GitHubCommitMismatchError,
    GitHubConfigurationError,
)
from app.schemas.github import PullRequestContext

logger = logging.getLogger(__name__)


class GitHubService:
    """Orchestrates GitHub App authentication and Pull Request context extraction."""

    def __init__(
        self,
        authenticator: GitHubAppAuthenticator | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize GitHubService.

        Args:
            authenticator: Optional injected GitHubAppAuthenticator.
            http_client: Optional injected httpx.AsyncClient.
        """
        self.authenticator = (
            authenticator
            if authenticator is not None
            else GitHubAppAuthenticator(http_client=http_client)
        )
        self._http_client = http_client

    def is_configured(self) -> bool:
        """Return True if GitHub App authentication is configured."""
        return self.authenticator.is_configured

    async def get_pull_request_context(
        self,
        repo_full_name: str,
        pr_number: int,
        expected_head_sha: str,
        expected_base_sha: str | None = None,
        installation_id: int | None = None,
    ) -> PullRequestContext:
        """Retrieve, verify, and normalize Pull Request context from GitHub.

        Args:
            repo_full_name: Full repository name (e.g. 'octocat/Hello-World').
            pr_number: Pull request number.
            expected_head_sha: Expected 40-character commit SHA at PR head.
            expected_base_sha: Optional expected 40-character commit SHA at PR base.
            installation_id: GitHub App installation ID. Falls back to settings.

        Returns:
            PullRequestContext: Canonical verified context model.

        Raises:
            GitHubConfigurationError: If installation ID is missing or app unconfigured.
            GitHubCommitMismatchError: If retrieved head SHA does not match expected_head_sha.
            GitHubError: On upstream GitHub REST or authentication failures.
        """
        settings = get_settings()
        resolved_installation_id = (
            installation_id
            if installation_id is not None
            else settings.GITHUB_APP_INSTALLATION_ID
        )

        if resolved_installation_id is None or resolved_installation_id <= 0:
            raise GitHubConfigurationError(
                "GitHub App installation ID is required but was not provided or configured."
            )

        # 1. Obtain ephemeral installation access token
        token_model = await self.authenticator.get_installation_token(
            resolved_installation_id
        )

        # 2. Interact with GitHub REST API
        async with GitHubClient(
            token=token_model.token,
            base_url=settings.GITHUB_API_BASE_URL,
            timeout=settings.GITHUB_API_TIMEOUT_SECONDS,
            http_client=self._http_client,
        ) as client:
            # 2a. Fetch PR metadata
            metadata = await client.get_pull_request(repo_full_name, pr_number)

            # 2b. Strict commit SHA consistency check
            if metadata.head_sha.lower() != expected_head_sha.lower():
                logger.error(
                    "PR head SHA mismatch for %s #%d: expected %s, retrieved %s",
                    repo_full_name,
                    pr_number,
                    expected_head_sha,
                    metadata.head_sha,
                )
                raise GitHubCommitMismatchError(
                    message=(
                        f"Commit SHA mismatch for {repo_full_name} PR #{pr_number}: "
                        f"expected {expected_head_sha}, but GitHub PR head is {metadata.head_sha}"
                    ),
                    expected_sha=expected_head_sha,
                    retrieved_sha=metadata.head_sha,
                )

            if (
                expected_base_sha
                and metadata.base_sha.lower() != expected_base_sha.lower()
            ):
                logger.warning(
                    "PR base SHA differs for %s #%d: expected %s, retrieved %s",
                    repo_full_name,
                    pr_number,
                    expected_base_sha,
                    metadata.base_sha,
                )

            # 2c. Fetch changed files
            files = await client.get_pull_request_files(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                max_files=settings.MAX_REVIEW_FILES,
            )

            # 2d. Fetch raw unified diff
            raw_diff = await client.get_pull_request_diff(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                max_bytes=settings.GITHUB_MAX_DIFF_BYTES,
            )

        # 3. Parse unified diff using existing deterministic parser (Rule FR-02)
        parsed_diff = DiffParser.parse(raw_diff)

        # 4. Assemble and return strongly typed PullRequestContext
        context = PullRequestContext(
            repository_id=metadata.repository_id,
            repository_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=expected_head_sha,
            base_sha=metadata.base_sha,
            metadata=metadata,
            files=files,
            parsed_diff=parsed_diff,
            raw_diff=raw_diff,
        )

        logger.info(
            "Extracted PR context for %s #%d (head=%s): %d files, %d diff hunks",
            repo_full_name,
            pr_number,
            expected_head_sha,
            len(files),
            parsed_diff.total_hunks,
        )

        return context


def get_github_service() -> GitHubService:
    """FastAPI and worker dependency provider returning a GitHubService instance."""
    return GitHubService()
