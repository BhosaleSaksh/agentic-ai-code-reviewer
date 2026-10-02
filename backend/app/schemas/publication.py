"""Canonical schemas for GitHub review publication and feedback collection.

Defines typed data contracts for:
- GitHub PR review and comment payloads
- Publication execution results and summary audit records
- Reviewer feedback, dismissals, and reactions for evaluation
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import (
    FeedbackSource,
    FeedbackType,
    FindingSide,
    PublishStatus,
)


class GitHubCommentPayload(BaseModel):
    """Payload representing an individual inline diff comment for GitHub PR Reviews API."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    path: str = Field(
        ...,
        min_length=1,
        description="Relative file path within the repository",
    )
    line: int = Field(
        ...,
        ge=1,
        description="Line number in the diff to anchor the review comment",
    )
    side: FindingSide = Field(
        default=FindingSide.RIGHT,
        description="Diff side: RIGHT for added/modified, LEFT for deleted",
    )
    body: str = Field(
        ...,
        min_length=1,
        description="Markdown-formatted comment text",
    )
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="Start line number for multi-line comments",
    )
    start_side: FindingSide | None = Field(
        default=None,
        description="Diff side for the start of multi-line comments",
    )


class GitHubReviewPayload(BaseModel):
    """Payload for creating a pull request review with multiple inline comments."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    commit_id: str = Field(
        ...,
        min_length=40,
        max_length=40,
        description="40-character commit SHA being reviewed",
    )
    body: str = Field(
        ...,
        min_length=1,
        description="Top-level review summary body markdown",
    )
    event: Literal["COMMENT", "APPROVE", "REQUEST_CHANGES"] = Field(
        default="COMMENT",
        description="Review decision event",
    )
    comments: list[GitHubCommentPayload] = Field(
        default_factory=list,
        description="List of inline review comments to post atomically with the review",
    )


class PublicationResult(BaseModel):
    """Result of an individual finding publication attempt."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    finding_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the finding published or skipped",
    )
    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Deterministic idempotency key for duplicate prevention",
    )
    status: PublishStatus = Field(
        ...,
        description="Resulting publication status",
    )
    github_comment_id: int | None = Field(
        default=None,
        description="GitHub comment ID if published successfully",
    )
    github_review_id: int | None = Field(
        default=None,
        description="GitHub review ID if associated with a review",
    )
    published_at: datetime | None = Field(
        default=None,
        description="Timestamp of publication completion",
    )
    failure_category: str | None = Field(
        default=None,
        description="Category of failure if publishing failed",
    )
    failure_message: str | None = Field(
        default=None,
        description="Sanitized failure description",
    )
    is_duplicate: bool = Field(
        default=False,
        description="True if publication was skipped due to idempotency",
    )


class ReviewPublicationSummary(BaseModel):
    """Comprehensive summary of a review publication run."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    review_run_id: uuid.UUID = Field(
        ...,
        description="Review run execution identifier",
    )
    repository_id: int = Field(
        ...,
        description="GitHub repository numeric ID",
    )
    pr_number: int = Field(
        ...,
        ge=1,
        description="Pull request number",
    )
    commit_sha: str = Field(
        ...,
        min_length=40,
        max_length=40,
        description="PR head commit SHA",
    )
    github_review_id: int | None = Field(
        default=None,
        description="GitHub review ID created for this run",
    )
    total_findings: int = Field(
        default=0,
        ge=0,
        description="Total findings received from pipeline",
    )
    verified_findings: int = Field(
        default=0,
        ge=0,
        description="Total findings with VERIFIED status",
    )
    rejected_findings: int = Field(
        default=0,
        ge=0,
        description="Findings rejected by critic or eligibility check",
    )
    published_comments: int = Field(
        default=0,
        ge=0,
        description="Total inline comments successfully published",
    )
    unanchored_comments: int = Field(
        default=0,
        ge=0,
        description="Findings that could not be anchored inline and fell back to summary",
    )
    skipped_comments: int = Field(
        default=0,
        ge=0,
        description="Total comments skipped (e.g. duplicate / ineligible)",
    )
    failed_comments: int = Field(
        default=0,
        ge=0,
        description="Total comments that failed during API publication",
    )
    results: list[PublicationResult] = Field(
        default_factory=list,
        description="Detailed result records for each finding",
    )


class FeedbackCreate(BaseModel):
    """Schema for recording reviewer feedback and interaction events."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    finding_id: uuid.UUID | None = Field(
        default=None,
        description="Associated finding ID if linked",
    )
    review_run_id: uuid.UUID | None = Field(
        default=None,
        description="Associated review run ID if linked",
    )
    repository_id: int = Field(
        ...,
        description="GitHub repository numeric ID",
    )
    pr_number: int = Field(
        ...,
        ge=1,
        description="Pull request number",
    )
    github_comment_id: int | None = Field(
        default=None,
        description="Target GitHub comment ID",
    )
    github_review_id: int | None = Field(
        default=None,
        description="Target GitHub review ID",
    )
    feedback_type: FeedbackType = Field(
        ...,
        description="Type of feedback event",
    )
    feedback_source: FeedbackSource = Field(
        default=FeedbackSource.GITHUB_WEBHOOK,
        description="Source of the feedback event",
    )
    reviewer_username: str | None = Field(
        default=None,
        max_length=100,
        description="GitHub login of the reviewer",
    )
    comment_body: str | None = Field(
        default=None,
        description="Reviewer reply or resolution message body",
    )
    extra_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Structured event metadata (e.g. reaction content)",
    )


class FeedbackResponse(FeedbackCreate):
    """Schema for returning persisted feedback audit records."""

    id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the feedback record",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the feedback was recorded",
    )


class FeedbackFilter(BaseModel):
    """Filter criteria for querying stored feedback records."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    repository_id: int | None = None
    pr_number: int | None = None
    finding_id: uuid.UUID | None = None
    review_run_id: uuid.UUID | None = None
    feedback_type: FeedbackType | None = None
