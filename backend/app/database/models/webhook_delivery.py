"""Webhook delivery domain model for idempotency and audit tracking."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WebhookDelivery(Base):
    """Tracks received GitHub webhook deliveries for deduplication and audit."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    delivery_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    action: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    repository_id: Mapped[int | None] = mapped_column(
        BigInteger,
        index=True,
        nullable=True,
    )
    repository_full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    pr_number: Mapped[int | None] = mapped_column(
        Integer,
        index=True,
        nullable=True,
    )
    head_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<WebhookDelivery(delivery_id='{self.delivery_id}', "
            f"event='{self.event_type}', status='{self.status}')>"
        )
