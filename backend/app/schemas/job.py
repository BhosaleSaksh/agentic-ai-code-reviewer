"""Pydantic schemas defining asynchronous review job contracts.

Provides strongly typed payloads and execution results for ARQ job queueing
and worker communication without exposing secrets or unbounded metadata.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ReviewJobPayload(BaseModel):
    """Strongly typed contract for enqueued code review jobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delivery_id: str = Field(
        description="Unique GitHub webhook delivery GUID",
        examples=["72d3162e-cc78-11e3-81ab-4c9367dc09d7"],
    )
    repository_id: int = Field(
        description="GitHub unique repository identifier",
        examples=[1296269],
    )
    repository_full_name: str = Field(
        description="Repository full owner/name identifier",
        examples=["octocat/Hello-World"],
    )
    pr_number: int = Field(
        description="Pull request number within the repository",
        examples=[42],
    )
    pull_request_id: int = Field(
        description="GitHub pull request identifier",
        examples=[990042],
    )
    head_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="40-character hexadecimal commit SHA at PR head",
        examples=["6dcb09b5b57875f334f61aebed695e2e4193db5e"],
    )
    base_sha: str = Field(
        pattern=r"^[0-9a-fA-F]{40}$",
        description="40-character hexadecimal commit SHA at PR base branch",
        examples=["1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"],
    )
    action: str = Field(
        description="Triggering event action (opened, synchronize, reopened)",
        examples=["opened"],
    )
    event_type: str = Field(
        default="pull_request",
        description="Triggering webhook event name",
        examples=["pull_request"],
    )
    installation_id: int | None = Field(
        default=None,
        description="GitHub App installation identifier if provided by webhook",
        examples=[12345678],
    )
    enqueued_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp when the job was enqueued",
    )


class ReviewJobResult(BaseModel):
    """Execution acknowledgement returned by review worker jobs."""

    model_config = ConfigDict(frozen=True)

    job_id: str = Field(
        description="ARQ unique job identifier",
        examples=["review:72d3162e-cc78-11e3-81ab-4c9367dc09d7"],
    )
    delivery_id: str = Field(
        description="Associated GitHub delivery ID",
        examples=["72d3162e-cc78-11e3-81ab-4c9367dc09d7"],
    )
    repository_full_name: str = Field(
        description="Target repository identifier",
        examples=["octocat/Hello-World"],
    )
    pr_number: int = Field(
        description="Target pull request number",
        examples=[42],
    )
    head_sha: str = Field(
        description="Evaluated commit SHA",
        examples=["6dcb09b5b57875f334f61aebed695e2e4193db5e"],
    )
    status: str = Field(
        default="acknowledged",
        description="Execution status ('acknowledged', 'completed', 'failed')",
        examples=["acknowledged"],
    )
    processed_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp when placeholder worker finished",
    )
