"""Asynchronous authenticated GitHub REST API client.

Provides strongly typed operations for retrieving Pull Request metadata, changed files,
and unified diffs with rate-limit tracking and explicit error handling.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Self

import httpx
from pydantic import SecretStr

from app.core.config import get_settings
from app.github.errors import (
    GitHubAuthenticationError,
    GitHubDiffTooLargeError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubServerError,
    GitHubUnprocessableEntityError,
)
from app.schemas.github import (
    GitHubPullRequestFile,
    GitHubPullRequestMetadata,
    GitHubRateLimitInfo,
)
from app.schemas.publication import GitHubReviewPayload

logger = logging.getLogger(__name__)


class GitHubClient:
    """Async client for interacting with the GitHub REST API using installation tokens."""

    def __init__(
        self,
        token: SecretStr | str,
        base_url: str | None = None,
        timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize GitHub REST client.

        Args:
            token: Installation access token (SecretStr or str).
            base_url: GitHub API base URL (default https://api.github.com).
            timeout: Request timeout in seconds.
            http_client: Optional injected httpx.AsyncClient (for testing/lifespan).
        """
        settings = get_settings()
        self._token = (
            token.get_secret_value() if isinstance(token, SecretStr) else str(token)
        )
        self._base_url = (
            base_url.rstrip("/")
            if base_url
            else settings.GITHUB_API_BASE_URL.rstrip("/")
        )
        self._timeout = (
            timeout if timeout is not None else settings.GITHUB_API_TIMEOUT_SECONDS
        )
        self._injected_client = http_client
        self._internal_client: httpx.AsyncClient | None = None
        self._last_rate_limit: GitHubRateLimitInfo | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close internal HTTP client if one was created."""
        if self._internal_client is not None:
            await self._internal_client.aclose()
            self._internal_client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the active HTTP client or lazily instantiate internal one."""
        if self._injected_client is not None:
            return self._injected_client
        if self._internal_client is None:
            self._internal_client = httpx.AsyncClient(timeout=self._timeout)
        return self._internal_client

    def _get_headers(
        self,
        accept: str = "application/vnd.github+json",
    ) -> dict[str, str]:
        """Generate authenticated request headers."""
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentic-ai-code-reviewer",
        }

    def _record_rate_limit(self, headers: httpx.Headers) -> None:
        """Extract and record rate-limit status from GitHub response headers."""
        limit_str = headers.get("x-ratelimit-limit")
        remaining_str = headers.get("x-ratelimit-remaining")
        reset_str = headers.get("x-ratelimit-reset")

        if limit_str and remaining_str and reset_str:
            try:
                limit = int(limit_str)
                remaining = int(remaining_str)
                reset_timestamp = int(reset_str)
                reset_at = datetime.fromtimestamp(reset_timestamp, tz=UTC)
                used = int(headers.get("x-ratelimit-used", "0"))
                resource = headers.get("x-ratelimit-resource")

                self._last_rate_limit = GitHubRateLimitInfo(
                    limit=limit,
                    remaining=remaining,
                    reset_at=reset_at,
                    used=used,
                    resource=resource,
                )
            except (ValueError, TypeError):
                pass

    def get_last_rate_limit(self) -> GitHubRateLimitInfo | None:
        """Return the most recently recorded rate-limit information."""
        return self._last_rate_limit

    def _handle_response_status(
        self,
        response: httpx.Response,
        endpoint_context: str,
    ) -> None:
        """Evaluate HTTP status and raise appropriate typed GitHub exceptions."""
        self._record_rate_limit(response.headers)

        if response.is_success:
            return

        status_code = response.status_code

        if status_code == 401:
            logger.error("GitHub REST API 401 Unauthorized: %s", endpoint_context)
            raise GitHubAuthenticationError(
                f"GitHub API authentication rejected for {endpoint_context}"
            )

        if status_code == 403:
            # Check if 403 is due to rate limiting
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining == "0" or "rate limit" in response.text.lower():
                reset_at = None
                if self._last_rate_limit:
                    reset_at = self._last_rate_limit.reset_at
                logger.warning(
                    "GitHub rate limit exceeded (HTTP 403): %s", endpoint_context
                )
                raise GitHubRateLimitError(
                    f"GitHub API rate limit exceeded for {endpoint_context}",
                    reset_at=reset_at,
                )
            logger.error("GitHub REST API 403 Forbidden: %s", endpoint_context)
            raise GitHubPermissionError(
                f"GitHub API permission denied for {endpoint_context}"
            )

        if status_code == 404:
            logger.error("GitHub REST API 404 Not Found: %s", endpoint_context)
            raise GitHubNotFoundError(
                f"GitHub resource was not found: {endpoint_context}"
            )

        if status_code == 422:
            logger.error("GitHub REST API 422 Unprocessable: %s", endpoint_context)
            errors: list[dict[str, Any]] = []
            try:
                data = response.json()
                if isinstance(data, dict):
                    errors = data.get("errors", [])
            except Exception:
                pass
            raise GitHubUnprocessableEntityError(
                f"GitHub API could not process request for {endpoint_context}",
                errors=errors,
            )

        if status_code == 429:
            logger.warning(
                "GitHub REST API 429 Too Many Requests: %s", endpoint_context
            )
            raise GitHubRateLimitError(
                f"GitHub API rate limit hit (HTTP 429) for {endpoint_context}"
            )

        if status_code >= 500:
            logger.error(
                "GitHub REST API server failure (HTTP %d): %s",
                status_code,
                endpoint_context,
            )
            raise GitHubServerError(
                f"GitHub server error (HTTP {status_code}) for {endpoint_context}",
                status_code=status_code,
            )

        logger.error(
            "Unexpected HTTP %d from GitHub API: %s",
            status_code,
            endpoint_context,
        )
        raise GitHubResponseError(
            f"Unexpected HTTP {status_code} received from GitHub for {endpoint_context}"
        )

    async def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> GitHubPullRequestMetadata:
        """Retrieve Pull Request metadata from GitHub.

        Args:
            repo_full_name: Full repository name (e.g. 'octocat/Hello-World').
            pr_number: Pull request number.

        Returns:
            GitHubPullRequestMetadata: Strongly typed PR metadata model.
        """
        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()

        try:
            response = await client.get(url, headers=self._get_headers())
        except httpx.TimeoutException as exc:
            logger.error("Timeout fetching PR metadata: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout fetching PR metadata for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error fetching PR metadata: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure fetching PR metadata for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, endpoint)

        try:
            data = response.json()
            head_dict = data.get("head", {})
            base_dict = data.get("base", {})
            base_repo = base_dict.get("repo", {}) or data.get("base", {}).get(
                "repo", {}
            )
            repo_id = base_repo.get("id") or data.get("head", {}).get("repo", {}).get(
                "id", 0
            )

            created_at = None
            if data.get("created_at"):
                created_at = datetime.fromisoformat(
                    data["created_at"].replace("Z", "+00:00")
                )

            updated_at = None
            if data.get("updated_at"):
                updated_at = datetime.fromisoformat(
                    data["updated_at"].replace("Z", "+00:00")
                )

            return GitHubPullRequestMetadata(
                repository_id=int(repo_id),
                repository_full_name=repo_full_name,
                pr_number=pr_number,
                pr_id=int(data["id"]),
                title=str(data.get("title", "")),
                state=str(data.get("state", "open")),
                head_sha=str(head_dict["sha"]),
                base_sha=str(base_dict["sha"]),
                head_branch=str(head_dict.get("ref", "")),
                base_branch=str(base_dict.get("ref", "")),
                html_url=data.get("html_url"),
                author=data.get("user", {}).get("login"),
                created_at=created_at,
                updated_at=updated_at,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("Malformed PR metadata payload from GitHub: %s", exc)
            raise GitHubResponseError(
                f"Malformed PR metadata returned by GitHub for {endpoint}"
            ) from exc

    async def get_pull_request_files(
        self,
        repo_full_name: str,
        pr_number: int,
        max_files: int | None = None,
    ) -> list[GitHubPullRequestFile]:
        """Retrieve list of modified files in the pull request.

        Args:
            repo_full_name: Full repository name (e.g. 'octocat/Hello-World').
            pr_number: Pull request number.
            max_files: Maximum files to return (defaults to MAX_REVIEW_FILES setting).

        Returns:
            list[GitHubPullRequestFile]: List of changed file models.
        """
        settings = get_settings()
        file_limit = max_files if max_files is not None else settings.MAX_REVIEW_FILES

        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}/files"
        client = self._get_client()

        files: list[GitHubPullRequestFile] = []
        page = 1
        per_page = 100

        while len(files) < file_limit:
            url = f"{self._base_url}/{endpoint}?per_page={per_page}&page={page}"
            try:
                response = await client.get(url, headers=self._get_headers())
            except httpx.TimeoutException as exc:
                logger.error("Timeout fetching PR files: %s (page %d)", endpoint, page)
                raise GitHubNetworkError(
                    f"Timeout fetching PR files for {endpoint}"
                ) from exc
            except httpx.RequestError as exc:
                logger.error(
                    "Network error fetching PR files: %s (page %d)", endpoint, page
                )
                raise GitHubNetworkError(
                    f"Network failure fetching PR files for {endpoint}: {type(exc).__name__}"
                ) from exc

            self._handle_response_status(response, f"{endpoint} (page {page})")

            try:
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError(f"Expected list of files, received {type(data)}")

                if not data:
                    break

                for item in data:
                    files.append(
                        GitHubPullRequestFile(
                            filename=str(item["filename"]),
                            status=str(item.get("status", "modified")),
                            additions=int(item.get("additions", 0)),
                            deletions=int(item.get("deletions", 0)),
                            changes=int(item.get("changes", 0)),
                            blob_url=item.get("blob_url"),
                            raw_url=item.get("raw_url"),
                            patch=item.get("patch"),
                            previous_filename=item.get("previous_filename"),
                        )
                    )
                    if len(files) >= file_limit:
                        break

                if len(data) < per_page:
                    break
                page += 1
            except (KeyError, ValueError, TypeError) as exc:
                logger.error("Malformed PR files payload from GitHub: %s", exc)
                raise GitHubResponseError(
                    f"Malformed PR files returned by GitHub for {endpoint}"
                ) from exc

        return files

    async def get_pull_request_diff(
        self,
        repo_full_name: str,
        pr_number: int,
        max_bytes: int | None = None,
    ) -> str:
        """Retrieve unified diff text for the pull request.

        Args:
            repo_full_name: Full repository name (e.g. 'octocat/Hello-World').
            pr_number: Pull request number.
            max_bytes: Maximum allowed diff byte count before raising an error.

        Returns:
            str: Raw unified diff string.

        Raises:
            GitHubDiffTooLargeError: If diff size exceeds max_bytes.
        """
        settings = get_settings()
        byte_limit = (
            max_bytes if max_bytes is not None else settings.GITHUB_MAX_DIFF_BYTES
        )

        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()

        headers = self._get_headers(accept="application/vnd.github.v3.diff")

        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout fetching PR diff: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout fetching PR diff for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error fetching PR diff: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure fetching PR diff for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, f"{endpoint} (diff)")

        diff_bytes = len(response.content)
        if diff_bytes > byte_limit:
            logger.warning(
                "PR diff for %s #%d exceeds safety limit: %d bytes > %d max bytes",
                repo_full_name,
                pr_number,
                diff_bytes,
                byte_limit,
            )
            raise GitHubDiffTooLargeError(
                message=(
                    f"PR diff for {repo_full_name} #{pr_number} exceeds safety boundary "
                    f"({diff_bytes} bytes > {byte_limit} bytes)"
                ),
                byte_count=diff_bytes,
                max_bytes=byte_limit,
            )

        return response.text

    async def create_pull_request_review(
        self,
        repo_full_name: str,
        pr_number: int,
        payload: GitHubReviewPayload | dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a pull request review with optional inline review comments.

        Args:
            repo_full_name: Target repository in 'owner/repo' format.
            pr_number: Target pull request number.
            payload: Review payload containing commit_id, body, event, and comments.

        Returns:
            dict[str, Any]: The created GitHub Review resource representation.
        """
        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}/reviews"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()

        if isinstance(payload, GitHubReviewPayload):
            body_data = payload.model_dump(exclude_none=True)
        else:
            body_data = dict(payload)

        headers = self._get_headers()

        try:
            response = await client.post(url, headers=headers, json=body_data)
        except httpx.TimeoutException as exc:
            logger.error("Timeout submitting PR review: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout submitting PR review for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error submitting PR review: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure submitting PR review for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, endpoint)

        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Expected JSON object")
            return result
        except Exception as exc:
            logger.error("Failed to parse JSON response for PR review: %s", endpoint)
            raise GitHubResponseError(
                f"Invalid JSON returned from GitHub API for {endpoint}"
            ) from exc

    async def create_pull_request_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
        start_line: int | None = None,
        start_side: str | None = None,
    ) -> dict[str, Any]:
        """Create an individual review comment on a pull request diff.

        Args:
            repo_full_name: Target repository in 'owner/repo' format.
            pr_number: Target pull request number.
            body: Comment text markdown.
            commit_id: SHA of the commit being commented on.
            path: Relative file path in the repository.
            line: Diff line number to attach comment to.
            side: RIGHT (new) or LEFT (old).
            start_line: Optional starting line for multi-line comments.
            start_side: Optional side for multi-line start.

        Returns:
            dict[str, Any]: Created comment representation from GitHub.
        """
        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}/comments"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()

        payload: dict[str, Any] = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
            "side": side,
        }
        if start_line is not None:
            payload["start_line"] = start_line
            payload["start_side"] = start_side or side

        headers = self._get_headers()

        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            logger.error("Timeout posting PR review comment: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout posting PR review comment for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error posting PR review comment: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure posting PR comment for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, endpoint)

        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Expected JSON object")
            return result
        except Exception as exc:
            logger.error("Failed to parse comment response JSON: %s", endpoint)
            raise GitHubResponseError(
                f"Invalid JSON returned from GitHub API for {endpoint}"
            ) from exc

    async def create_issue_comment(
        self,
        repo_full_name: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Create a general comment on an issue or pull request conversation thread.

        Args:
            repo_full_name: Target repository in 'owner/repo' format.
            issue_number: Target issue or pull request number.
            body: Comment text markdown.

        Returns:
            dict[str, Any]: Created issue comment representation.
        """
        endpoint = f"repos/{repo_full_name}/issues/{issue_number}/comments"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()
        headers = self._get_headers()

        try:
            response = await client.post(url, headers=headers, json={"body": body})
        except httpx.TimeoutException as exc:
            logger.error("Timeout posting issue comment: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout posting issue comment for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error posting issue comment: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure posting issue comment for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, endpoint)

        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Expected JSON object")
            return result
        except Exception as exc:
            logger.error("Failed to parse issue comment JSON: %s", endpoint)
            raise GitHubResponseError(
                f"Invalid JSON returned from GitHub API for {endpoint}"
            ) from exc

    async def list_pull_request_comments(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """List all review comments on the specified pull request.

        Args:
            repo_full_name: Target repository in 'owner/repo' format.
            pr_number: Target pull request number.

        Returns:
            list[dict[str, Any]]: List of review comment objects.
        """
        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}/comments"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()
        headers = self._get_headers()

        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout fetching PR comments: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout fetching PR comments for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error fetching PR comments: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure fetching PR comments for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, endpoint)

        try:
            result = response.json()
            if not isinstance(result, list):
                raise ValueError("Expected JSON list")
            return result
        except Exception as exc:
            logger.error("Failed to parse PR comments JSON: %s", endpoint)
            raise GitHubResponseError(
                f"Invalid JSON list returned from GitHub API for {endpoint}"
            ) from exc

    async def list_pull_request_reviews(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """List all submitted reviews on the specified pull request.

        Args:
            repo_full_name: Target repository in 'owner/repo' format.
            pr_number: Target pull request number.

        Returns:
            list[dict[str, Any]]: List of review objects.
        """
        endpoint = f"repos/{repo_full_name}/pulls/{pr_number}/reviews"
        url = f"{self._base_url}/{endpoint}"
        client = self._get_client()
        headers = self._get_headers()

        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout fetching PR reviews: %s", endpoint)
            raise GitHubNetworkError(
                f"Timeout fetching PR reviews for {endpoint}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error fetching PR reviews: %s", endpoint)
            raise GitHubNetworkError(
                f"Network failure fetching PR reviews for {endpoint}: {type(exc).__name__}"
            ) from exc

        self._handle_response_status(response, endpoint)

        try:
            result = response.json()
            if not isinstance(result, list):
                raise ValueError("Expected JSON list")
            return result
        except Exception as exc:
            logger.error("Failed to parse PR reviews JSON: %s", endpoint)
            raise GitHubResponseError(
                f"Invalid JSON list returned from GitHub API for {endpoint}"
            ) from exc
