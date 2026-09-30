"""ReviewRun domain model representing a review pipeline execution."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.database.models.evidence_item import EvidenceItem
    from app.database.models.finding import Finding
    from app.database.models.pull_request import PullRequest


class ReviewRun(Base):
    """ReviewRun entity tracking individual code review pipeline executions."""

    __tablename__ = "review_runs"
    __table_args__ = (
        UniqueConstraint(
            "pull_request_id",
            "commit_sha",
            name="uq_review_runs_pr_commit",
        ),
        Index(
            "idx_review_runs_pr_status",
            "pull_request_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    commit_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="QUEUED",
        server_default="QUEUED",
        nullable=False,
    )
    trigger_type: Mapped[str] = mapped_column(
        String(30),
        default="WEBHOOK",
        server_default="WEBHOOK",
        nullable=False,
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        default=Decimal("0.0000"),
        server_default="0.0000",
        nullable=False,
    )
    latency_seconds: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )
    review_plan: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    error_log: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship(
        "PullRequest",
        back_populates="review_runs",
        lazy="selectin",
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        "EvidenceItem",
        back_populates="review_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    findings: Mapped[list["Finding"]] = relationship(
        "Finding",
        back_populates="review_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ReviewRun(id={self.id}, pr_id={self.pull_request_id}, status='{self.status}')>"
