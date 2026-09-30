"""Finding domain model representing candidate and verified code review findings."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.database.models.evidence_item import EvidenceItem
    from app.database.models.review_run import ReviewRun


class Finding(Base):
    """Finding entity tracking candidate and verified code review findings.

    Corresponds to the canonical ReviewFinding schema while supporting persistence
    lifecycle tracking (agent origin, critic verification, and GitHub publication).
    """

    __tablename__ = "findings"
    __table_args__ = (
        Index(
            "idx_findings_run_status",
            "review_run_id",
            "verification_status",
        ),
        Index(
            "idx_findings_run_file",
            "review_run_id",
            "file_path",
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
    agent_name: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    issue_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        String(10),
        default="RIGHT",
        server_default="RIGHT",
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    recommendation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    suggested_patch: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0.0",
        nullable=False,
    )
    raw_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    verification_status: Mapped[str] = mapped_column(
        String(50),
        default="UNVERIFIED",
        server_default="UNVERIFIED",
        nullable=False,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    critic_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    github_comment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    publish_status: Mapped[str] = mapped_column(
        String(30),
        default="UNPUBLISHED",
        server_default="UNPUBLISHED",
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
    review_run: Mapped["ReviewRun"] = relationship(
        "ReviewRun",
        back_populates="findings",
        lazy="selectin",
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        "EvidenceItem",
        back_populates="finding",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Finding(id={self.id}, run_id={self.review_run_id}, "
            f"type='{self.issue_type}', severity='{self.severity}', status='{self.verification_status}')>"
        )
