"""PullRequest domain model representing an ingested GitHub pull request."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.database.models.repository import Repository
    from app.database.models.review_run import ReviewRun


class PullRequest(Base):
    """PullRequest entity tracking pull request metadata and changes."""

    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "pr_number",
            name="uq_pull_requests_repo_pr_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    author: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    base_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    head_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(30),
        default="open",
        server_default="open",
        nullable=False,
    )
    additions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    deletions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    changed_files_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(
        "Repository",
        back_populates="pull_requests",
        lazy="selectin",
    )
    review_runs: Mapped[list["ReviewRun"]] = relationship(
        "ReviewRun",
        back_populates="pull_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<PullRequest(id={self.id}, repo_id={self.repository_id}, pr_number={self.pr_number})>"
