"""Pydantic schemas for GitHub webhook event payloads and responses.

Provides strongly typed models for validating pull request webhook payloads
and structured HTTP response envelopes while gracefully ignoring unrelated
GitHub payload metadata.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebhookRepository(BaseModel):
    """Repository metadata extracted from GitHub webhook payload."""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="GitHub repository identifier")
    name: str = Field(description="Repository short name")
    full_name: str = Field(description="Repository full owner/name identifier")
    html_url: str | None = Field(default=None, description="Repository HTML URL")
    default_branch: str | None = Field(
        default="main", description="Default branch name"
    )


class WebhookCommit(BaseModel):
    """Git commit reference extracted from PR head or base."""

    model_config = ConfigDict(extra="ignore")

    sha: str = Field(description="40-character hexadecimal commit SHA")
    ref: str | None = Field(default=None, description="Branch or reference name")


class WebhookUser(BaseModel):
    """GitHub user metadata extracted from PR or sender."""

    model_config = ConfigDict(extra="ignore")

    login: str | None = Field(default=None, description="GitHub username")
    id: int | None = Field(default=None, description="GitHub user ID")


class WebhookPullRequest(BaseModel):
    """Pull request entity metadata from GitHub webhook payload."""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="GitHub pull request ID")
    number: int = Field(description="Pull request number within the repository")
    title: str | None = Field(default=None, description="Pull request title")
    state: str = Field(default="open", description="Pull request state")
    head: WebhookCommit = Field(description="Head commit reference")
    base: WebhookCommit = Field(description="Base commit reference")
    html_url: str | None = Field(default=None, description="PR HTML web URL")
    user: WebhookUser | None = Field(default=None, description="PR author")


class WebhookInstallation(BaseModel):
    """GitHub App installation metadata from webhook payload."""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="GitHub App installation ID")


class PullRequestWebhookPayload(BaseModel):
    """Validated pull_request webhook event payload."""

    model_config = ConfigDict(extra="ignore")

    action: str = Field(
        description="Pull request action (e.g. opened, synchronize, reopened)"
    )
    number: int = Field(description="Pull request number")
    pull_request: WebhookPullRequest = Field(
        description="Enclosed pull request details"
    )
    repository: WebhookRepository = Field(description="Enclosing repository details")
    sender: WebhookUser | None = Field(
        default=None, description="User who triggered the event"
    )
    installation: WebhookInstallation | None = Field(
        default=None, description="GitHub App installation details"
    )


class GenericWebhookPayload(BaseModel):
    """Permissive payload model for non-PR or unknown GitHub events."""

    model_config = ConfigDict(extra="ignore")

    action: str | None = Field(default=None, description="Event action if present")
    repository: dict[str, Any] | None = Field(
        default=None, description="Repository metadata if present"
    )


class WebhookResponse(BaseModel):
    """Standardized response contract for webhook ingestion."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        description="Ingestion result: 'accepted', 'ignored', or 'duplicate'",
        examples=["accepted", "ignored", "duplicate"],
    )
    delivery_id: str = Field(
        description="GitHub delivery UUID for idempotency tracking",
        examples=["72d3162e-cc78-11e3-81ab-4c9367dc09d7"],
    )
    event: str = Field(
        description="GitHub event name from X-GitHub-Event",
        examples=["pull_request", "ping"],
    )
    action: str | None = Field(
        default=None,
        description="Event action if applicable",
        examples=["opened", "synchronize", "reopened"],
    )
    message: str = Field(
        description="Human-readable processing summary",
        examples=["Pull request review event accepted for processing"],
    )
