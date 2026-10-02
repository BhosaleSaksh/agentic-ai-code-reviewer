"""ReviewPublication domain model tracking GitHub PR review comments and reviews."""

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


class ReviewPublication(Base):
    """ReviewPublication entity recording GitHub review and comment publication events.

    Provides a tamper-evident audit trail of every review comment or review summary
    posted to GitHub, enforcing strict idempotency and tracking failure reasons.
    """

    __tablename__ = "review_publications"
    __table_args__ = (
        Index(
            "idx_publications_run_status",
            "review_run_id",
            "publication_status",
        ),
        Index(
            "idx_publications_repo_pr",
            "repository_id",
            "pr_number",
        ),
        Index(
            "idx_publications_idempotency",
            "idempotency_key",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    review_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("findings.id", ondelete="SET NULL"),
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
    commit_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    github_review_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    github_comment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    publication_status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING",
        server_default="PENDING",
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failure_category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    failure_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    comment_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
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
    review_run: Mapped["ReviewRun"] = relationship(
        "ReviewRun",
        back_populates="publications",
        lazy="selectin",
    )
    finding: Mapped["Finding | None"] = relationship(
        "Finding",
        back_populates="publications",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewPublication(id={self.id}, run_id={self.review_run_id}, "
            f"finding_id={self.finding_id}, status='{self.publication_status}')>"
        )
