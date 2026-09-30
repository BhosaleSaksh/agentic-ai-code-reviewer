"""0002_webhook_deliveries

Revision ID: b2f69a12c841
Revises: 01e79a94e743
Create Date: 2026-09-30 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f69a12c841"
down_revision: str | Sequence[str] | None = "01e79a94e743"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to include webhook_deliveries table."""
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("repository_full_name", sa.String(length=255), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("head_sha", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_delivery_id"),
        "webhook_deliveries",
        ["delivery_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_webhook_deliveries_repository_id"),
        "webhook_deliveries",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_deliveries_pr_number"),
        "webhook_deliveries",
        ["pr_number"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema removing webhook_deliveries table."""
    op.drop_index(
        op.f("ix_webhook_deliveries_pr_number"),
        table_name="webhook_deliveries",
    )
    op.drop_index(
        op.f("ix_webhook_deliveries_repository_id"),
        table_name="webhook_deliveries",
    )
    op.drop_index(
        op.f("ix_webhook_deliveries_delivery_id"),
        table_name="webhook_deliveries",
    )
    op.drop_table("webhook_deliveries")
