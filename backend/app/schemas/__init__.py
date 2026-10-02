"""Canonical Pydantic v2 schemas for the review pipeline.

Exports all data contracts, evidence models, planning objects,
diff representations, and enumerations.
"""

from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import (
    DiffLineType,
    EvidenceType,
    FeedbackSource,
    FeedbackType,
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
from app.schemas.publication import (
    FeedbackCreate,
    FeedbackFilter,
    FeedbackResponse,
    GitHubCommentPayload,
    GitHubReviewPayload,
    PublicationResult,
    ReviewPublicationSummary,
)
from app.schemas.review_plan import ReviewPlan
from app.schemas.static_analysis import (
    BanditFinding,
    BanditResult,
    PipAuditFinding,
    PipAuditResult,
    SemgrepFinding,
    SemgrepResult,
    StaticAnalysisExecutionStatus,
    ToolAnalysisSummary,
)
from app.schemas.verification import (
    CriticStructuredOutput,
    EvidenceMatch,
    VerificationContext,
    VerificationResult,
)
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
    "FeedbackType",
    "FeedbackSource",
    "FileChangeType",
    "DiffLineType",
    "StaticAnalysisExecutionStatus",
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
    "SemgrepFinding",
    "SemgrepResult",
    "BanditFinding",
    "BanditResult",
    "PipAuditFinding",
    "PipAuditResult",
    "ToolAnalysisSummary",
    "EvidenceMatch",
    "VerificationContext",
    "VerificationResult",
    "CriticStructuredOutput",
    "GitHubCommentPayload",
    "GitHubReviewPayload",
    "PublicationResult",
    "ReviewPublicationSummary",
    "FeedbackCreate",
    "FeedbackResponse",
    "FeedbackFilter",
]
