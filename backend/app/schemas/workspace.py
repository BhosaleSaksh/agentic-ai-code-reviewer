"""Workspace context schemas for isolated local repository checkouts.

Defines the strongly typed, immutable representation of a verified local Git workspace
created for a specific Pull Request commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class WorkspaceContext(BaseModel):
    """Canonical representation of an isolated, commit-verified local repository workspace.

    Guarantees that the workspace directory exists, is bounded, is operating in
    detached HEAD mode, and strictly represents the expected commit SHA.
    """

    model_config = ConfigDict(frozen=True)

    workspace_id: str = Field(
        description="Unique identifier for this workspace instance",
    )
    workspace_path: Path = Field(
        description="Absolute filesystem path to the isolated repository root",
    )
    repository_id: int = Field(
        gt=0,
        description="Target repository identifier",
    )
    repository_full_name: str = Field(
        description="Target repository full name (owner/repo)",
    )
    pr_number: int = Field(
        gt=0,
        description="Pull request number being reviewed",
    )
    expected_head_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="Expected head commit SHA requested by the review job",
    )
    actual_head_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="Verified commit SHA currently checked out at HEAD in the workspace",
    )
    base_sha: str | None = Field(
        default=None,
        description="Expected base commit SHA if provided",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp when workspace was prepared",
    )
    size_bytes: int = Field(
        default=0,
        ge=0,
        description="Total disk space consumed by the workspace directory in bytes",
    )
    is_detached_head: bool = Field(
        default=True,
        description="Whether the workspace repository is operating in detached HEAD mode",
    )

    @model_validator(mode="after")
    def verify_commit_integrity(self) -> Self:
        """Enforce the fundamental invariant: actual_head_sha must match expected_head_sha."""
        if self.actual_head_sha.lower() != self.expected_head_sha.lower():
            from app.services.workspace_errors import WorkspaceCommitMismatchError

            raise WorkspaceCommitMismatchError(
                message=(
                    f"Workspace commit mismatch for {self.repository_full_name} PR #{self.pr_number}: "
                    f"expected {self.expected_head_sha}, but HEAD is at {self.actual_head_sha}"
                ),
                expected_sha=self.expected_head_sha,
                actual_sha=self.actual_head_sha,
            )
        return self
