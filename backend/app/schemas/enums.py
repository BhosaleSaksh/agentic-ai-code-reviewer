"""Canonical enumerations for the code review pipeline.

Defines typed string enums for finding categories, severity levels,
evidence types, diff coordinates, and review lifecycle stages.
"""

from enum import StrEnum


class IssueType(StrEnum):
    """Categorization of code review findings based on specialist domains."""

    SECURITY = "SECURITY"
    BUG_LOGIC = "BUG_LOGIC"
    ERROR_HANDLING = "ERROR_HANDLING"
    TEST_ADEQUACY = "TEST_ADEQUACY"
    PERFORMANCE = "PERFORMANCE"
    MAINTAINABILITY = "MAINTAINABILITY"


class Severity(StrEnum):
    """Severity classification for review findings."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingSide(StrEnum):
    """Diff side for GitHub review comments.

    RIGHT corresponds to added/modified lines in the new version.
    LEFT corresponds to deleted lines from the previous version.
    """

    RIGHT = "RIGHT"
    LEFT = "LEFT"


class VerificationStatus(StrEnum):
    """Verification lifecycle state assigned by the Critic Agent."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPPRESSED_FALSE_POSITIVE = "SUPPRESSED_FALSE_POSITIVE"
    DROPPED_LOW_CONFIDENCE = "DROPPED_LOW_CONFIDENCE"


class PublishStatus(StrEnum):
    """Publication state for GitHub review comments."""

    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DISMISSED = "DISMISSED"


class EvidenceType(StrEnum):
    """Category of grounding evidence supporting a finding."""

    DIFF_HUNK = "DIFF_HUNK"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    DEPENDENCY = "DEPENDENCY"
    AST_CONTEXT = "AST_CONTEXT"


class FileChangeType(StrEnum):
    """File status classification in a Git diff."""

    MODIFIED = "MODIFIED"
    ADDED = "ADDED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"
    BINARY = "BINARY"


class DiffLineType(StrEnum):
    """Type of a single line within a unified diff hunk."""

    ADDED = "ADDED"
    DELETED = "DELETED"
    CONTEXT = "CONTEXT"
