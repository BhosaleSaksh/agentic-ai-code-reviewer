"""Pydantic schemas for GitHub App authentication and Pull Request context.

Provides strongly typed data contracts for tokens, rate limits, PR metadata,
changed files, and normalized PR context models without leaking secrets.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.schemas.diff import ParsedDiff


def _utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class GitHubInstallationToken(BaseModel):
    """Temporary installation access token exchanged via GitHub App JWT."""

    model_config = ConfigDict(frozen=True)

    token: SecretStr = Field(
        description="Installation access token value (masked for safety)"
    )
    expires_at: datetime = Field(description="UTC expiration timestamp of the token")
    permissions: dict[str, str] = Field(
        default_factory=dict,
        description="Granted installation permission scopes",
    )
    repository_selection: str | None = Field(
        default=None,
        description="Repository selection scope ('all' or 'selected')",
    )

    @property
    def is_expired(self) -> bool:
        """Return True if token has expired or is within 60 seconds of expiration."""
        return _utc_now().timestamp() >= (self.expires_at.timestamp() - 60)


class GitHubRateLimitInfo(BaseModel):
    """Rate limit status extracted from GitHub API response headers."""

    model_config = ConfigDict(frozen=True)

    limit: int = Field(description="Maximum requests allowed in the current window")
    remaining: int = Field(description="Number of remaining requests in the window")
    reset_at: datetime = Field(description="UTC timestamp when the rate limit resets")
    used: int = Field(default=0, description="Number of requests consumed so far")
    resource: str | None = Field(
        default=None, description="Rate-limited resource family (e.g. core, search)"
    )


class GitHubPullRequestMetadata(BaseModel):
    """Normalized metadata describing the state of a GitHub Pull Request."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    repository_id: int = Field(description="GitHub repository identifier")
    repository_full_name: str = Field(
        description="Full repository name (e.g. 'octocat/Hello-World')"
    )
    pr_number: int = Field(description="Pull request number within the repository")
    pr_id: int = Field(description="GitHub unique pull request entity ID")
    title: str = Field(description="Pull request title")
    state: str = Field(
        default="open", description="Pull request state ('open', 'closed')"
    )
    head_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="40-character commit SHA at PR head branch",
    )
    base_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="40-character commit SHA at PR base branch",
    )
    head_branch: str = Field(description="PR head branch reference name")
    base_branch: str = Field(description="PR base branch reference name")
    html_url: str | None = Field(
        default=None, description="GitHub web page URL for the PR"
    )
    author: str | None = Field(
        default=None, description="GitHub username of the PR author"
    )
    created_at: datetime | None = Field(
        default=None, description="Creation timestamp from GitHub"
    )
    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp from GitHub"
    )


class GitHubPullRequestFile(BaseModel):
    """Metadata describing a single file changed in a pull request."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    filename: str = Field(description="Target relative file path in the repository")
    status: str = Field(
        description="Change status ('added', 'modified', 'removed', 'renamed', etc.)"
    )
    additions: int = Field(default=0, ge=0, description="Number of added lines")
    deletions: int = Field(default=0, ge=0, description="Number of deleted lines")
    changes: int = Field(default=0, ge=0, description="Total line changes")
    blob_url: str | None = Field(default=None, description="GitHub blob view URL")
    raw_url: str | None = Field(
        default=None, description="Raw file content download URL"
    )
    patch: str | None = Field(
        default=None, description="Unified diff patch for this file if available"
    )
    previous_filename: str | None = Field(
        default=None, description="Original filename if renamed or copied"
    )


class PullRequestContext(BaseModel):
    """Canonical, strongly typed representation of extracted PR review context."""

    model_config = ConfigDict(frozen=True)

    repository_id: int = Field(description="Target repository identifier")
    repository_full_name: str = Field(
        description="Repository full owner/name identifier"
    )
    pr_number: int = Field(description="Target pull request number")
    head_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="Expected head commit SHA that triggered the review",
    )
    base_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="Expected base commit SHA",
    )
    metadata: GitHubPullRequestMetadata = Field(
        description="Verified GitHub PR metadata"
    )
    files: list[GitHubPullRequestFile] = Field(
        default_factory=list,
        description="List of files altered by the pull request",
    )
    parsed_diff: ParsedDiff = Field(
        description="Structured, line-mapped unified diff hunks"
    )
    raw_diff: str = Field(
        default="",
        description="Raw unified diff text retrieved from GitHub",
    )
    extracted_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp when PR context was retrieved and verified",
    )

    @model_validator(mode="after")
    def verify_head_sha_consistency(self) -> Self:
        """Enforce strict consistency between expected head SHA and retrieved PR head SHA."""
        if self.metadata.head_sha.lower() != self.head_sha.lower():
            from app.github.errors import GitHubCommitMismatchError

            raise GitHubCommitMismatchError(
                message=(
                    f"Commit SHA mismatch for {self.repository_full_name} PR #{self.pr_number}: "
                    f"expected {self.head_sha}, but GitHub PR head is currently {self.metadata.head_sha}"
                ),
                expected_sha=self.head_sha,
                retrieved_sha=self.metadata.head_sha,
            )
        return self
