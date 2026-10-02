"""ReviewFeedback domain model tracking reviewer actions, dismissals, and reactions."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.database.models.finding import Finding
    from app.database.models.review_run import ReviewRun


class ReviewFeedback(Base):
    """ReviewFeedback entity capturing GitHub reviewer feedback and comment lifecycle events.

    Stores audit data for review reactions, comment dismissals, resolutions,
    and reviewer responses to support scientific evaluation of review quality.
    """

    __tablename__ = "review_feedback"
    __table_args__ = (
        Index(
            "idx_feedback_finding",
            "finding_id",
        ),
        Index(
            "idx_feedback_repo_pr",
            "repository_id",
            "pr_number",
        ),
        Index(
            "idx_feedback_type",
            "feedback_type",
        ),
        Index(
            "idx_feedback_comment",
            "github_comment_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("findings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    repository_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    github_comment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    github_review_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    feedback_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    feedback_source: Mapped[str] = mapped_column(
        String(50),
        default="GITHUB_WEBHOOK",
        server_default="GITHUB_WEBHOOK",
        nullable=False,
    )
    reviewer_username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    comment_body: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    review_run: Mapped["ReviewRun | None"] = relationship(
        "ReviewRun",
        back_populates="feedbacks",
        lazy="selectin",
    )
    finding: Mapped["Finding | None"] = relationship(
        "Finding",
        back_populates="feedbacks",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewFeedback(id={self.id}, finding_id={self.finding_id}, "
            f"type='{self.feedback_type}', source='{self.feedback_source}')>"
        )
