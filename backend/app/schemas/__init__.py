"""Canonical Pydantic v2 schemas for the review pipeline.

Exports all data contracts, evidence models, planning objects,
diff representations, and enumerations.
"""

from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    EvidenceType,
    FileChangeType,
    FindingSide,
    IssueType,
    PublishStatus,
    Severity,
    VerificationStatus,
)
from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.github import (
    GitHubInstallationToken,
    GitHubPullRequestFile,
    GitHubPullRequestMetadata,
    GitHubRateLimitInfo,
    PullRequestContext,
)
from app.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse
from app.schemas.job import ReviewJobPayload, ReviewJobResult
from app.schemas.review_plan import ReviewPlan
from app.schemas.webhook import (
    GenericWebhookPayload,
    PullRequestWebhookPayload,
    WebhookCommit,
    WebhookInstallation,
    WebhookPullRequest,
    WebhookRepository,
    WebhookResponse,
    WebhookUser,
)
from app.schemas.workspace import WorkspaceContext

__all__ = [
    # Enums
    "IssueType",
    "Severity",
    "FindingSide",
    "VerificationStatus",
    "PublishStatus",
    "EvidenceType",
    "FileChangeType",
    "DiffLineType",
    # Schemas
    "EvidenceModel",
    "ReviewFinding",
    "ReviewPlan",
    "DiffLine",
    "DiffHunk",
    "DiffFile",
    "ParsedDiff",
    "HealthResponse",
    "DependencyStatus",
    "ReadinessResponse",
    "WebhookRepository",
    "WebhookCommit",
    "WebhookUser",
    "WebhookPullRequest",
    "WebhookInstallation",
    "PullRequestWebhookPayload",
    "GenericWebhookPayload",
    "WebhookResponse",
    "ReviewJobPayload",
    "ReviewJobResult",
    "GitHubInstallationToken",
    "GitHubRateLimitInfo",
    "GitHubPullRequestMetadata",
    "GitHubPullRequestFile",
    "PullRequestContext",
    "WorkspaceContext",
]
