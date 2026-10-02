"""0003_github_publishing_and_feedback

Revision ID: c5e31d4e6f20
Revises: b2f69a12c841
Create Date: 2026-10-03 01:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5e31d4e6f20"
down_revision: str | Sequence[str] | None = "b2f69a12c841"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to include review_publications and review_feedback tables."""
    # 1. review_publications table
    op.create_table(
        "review_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_run_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("github_review_id", sa.BigInteger(), nullable=True),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "publication_status",
            sa.String(length=30),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_category", sa.String(length=50), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "comment_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_review_publications_finding_id_findings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["review_runs.id"],
            name=op.f("fk_review_publications_review_run_id_review_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_publications")),
    )
    op.create_index(
        "idx_publications_idempotency",
        "review_publications",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "idx_publications_repo_pr",
        "review_publications",
        ["repository_id", "pr_number"],
        unique=False,
    )
    op.create_index(
        "idx_publications_run_status",
        "review_publications",
        ["review_run_id", "publication_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_publications_finding_id"),
        "review_publications",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_publications_review_run_id"),
        "review_publications",
        ["review_run_id"],
        unique=False,
    )

    # 2. review_feedback table
    op.create_table(
        "review_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("review_run_id", sa.Uuid(), nullable=True),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("github_review_id", sa.BigInteger(), nullable=True),
        sa.Column("feedback_type", sa.String(length=50), nullable=False),
        sa.Column(
            "feedback_source",
            sa.String(length=50),
            server_default="GITHUB_WEBHOOK",
            nullable=False,
        ),
        sa.Column("reviewer_username", sa.String(length=100), nullable=True),
        sa.Column("comment_body", sa.Text(), nullable=True),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_review_feedback_finding_id_findings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_run_id"],
            ["review_runs.id"],
            name=op.f("fk_review_feedback_review_run_id_review_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_feedback")),
    )
    op.create_index(
        "idx_feedback_comment",
        "review_feedback",
        ["github_comment_id"],
        unique=False,
    )
    op.create_index(
        "idx_feedback_finding",
        "review_feedback",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        "idx_feedback_repo_pr",
        "review_feedback",
        ["repository_id", "pr_number"],
        unique=False,
    )
    op.create_index(
        "idx_feedback_type",
        "review_feedback",
        ["feedback_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_feedback_finding_id"),
        "review_feedback",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_feedback_review_run_id"),
        "review_feedback",
        ["review_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema removing review_feedback and review_publications tables."""
    # 1. Drop review_feedback
    op.drop_index(
        op.f("ix_review_feedback_review_run_id"),
        table_name="review_feedback",
    )
    op.drop_index(
        op.f("ix_review_feedback_finding_id"),
        table_name="review_feedback",
    )
    op.drop_index("idx_feedback_type", table_name="review_feedback")
    op.drop_index("idx_feedback_repo_pr", table_name="review_feedback")
    op.drop_index("idx_feedback_finding", table_name="review_feedback")
    op.drop_index("idx_feedback_comment", table_name="review_feedback")
    op.drop_table("review_feedback")

    # 2. Drop review_publications
    op.drop_index(
        op.f("ix_review_publications_review_run_id"),
        table_name="review_publications",
    )
    op.drop_index(
        op.f("ix_review_publications_finding_id"),
        table_name="review_publications",
    )
    op.drop_index(
        "idx_publications_run_status",
        table_name="review_publications",
    )
    op.drop_index(
        "idx_publications_repo_pr",
        table_name="review_publications",
    )
    op.drop_index(
        "idx_publications_idempotency",
        table_name="review_publications",
    )
    op.drop_table("review_publications")
