"""EvidenceItem domain model representing grounded evidence items."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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


class EvidenceItem(Base):
    """EvidenceItem entity tracking diff, static analysis, and context evidence."""

    __tablename__ = "evidence_items"
    __table_args__ = (
        Index(
            "idx_evidence_items_run_file",
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
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    content_snippet: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    rule_or_cve_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    corroborating_tool: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    # Named "metadata" in the database per architecture spec, mapped to extra_metadata
    # in Python to prevent collision with SQLAlchemy Base.metadata.
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    review_run: Mapped["ReviewRun"] = relationship(
        "ReviewRun",
        back_populates="evidence_items",
        lazy="selectin",
    )
    finding: Mapped["Finding | None"] = relationship(
        "Finding",
        back_populates="evidence_items",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<EvidenceItem(id={self.id}, run_id={self.review_run_id}, "
            f"type='{self.evidence_type}', file='{self.file_path}')>"
        )
