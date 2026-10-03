"""Normalized finding models and prediction-to-ground-truth match results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NormalizedFinding(BaseModel):
    """Standardized representation of a candidate finding across all baselines."""

    model_config = ConfigDict(extra="ignore")

    finding_id: str = Field(description="Unique identifier for the predicted finding")
    category: str = Field(description="Finding category (e.g. SECURITY, BUG_LOGIC)")
    severity: str = Field(
        default="MEDIUM",
        description="Predicted severity (CRITICAL, HIGH, MEDIUM, LOW, INFO)",
    )
    affected_file: str = Field(description="Target file path identified by reviewer")
    line_start: int = Field(ge=1, description="1-indexed starting line")
    line_end: int = Field(ge=1, description="1-indexed ending line")
    title: str = Field(description="Concise summary title of the issue")
    explanation: str = Field(description="Detailed explanation of the defect")
    confidence_score: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    is_verified: bool = Field(
        default=True,
        description="Whether the finding passed critic/verification stage",
    )
    verification_status: str | None = Field(
        default=None,
        description="Explicit verification status if verified by critic",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Reason for rejection if dropped by critic",
    )
    evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Grounded evidence items attached to this finding",
    )
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Unmodified baseline-specific output payload",
    )


class MatchResult(BaseModel):
    """Pairing outcome between a predicted finding and a ground-truth defect."""

    model_config = ConfigDict(extra="ignore")

    matched: bool = Field(description="True if finding meets all match criteria")
    ground_truth_id: str | None = Field(
        default=None,
        description="Matched ground-truth defect ID if successful",
    )
    predicted_finding_id: str = Field(
        description="ID of the predicted finding evaluated",
    )
    file_matched: bool = Field(
        default=False,
        description="Whether file paths matched (normalized)",
    )
    line_distance: int = Field(
        default=0,
        description="Distance between predicted line and ground-truth range",
    )
    category_matched: bool = Field(
        default=False,
        description="Whether issue category matched ground-truth expectation",
    )
    semantic_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated semantic similarity or overlap score",
    )
    is_duplicate: bool = Field(
        default=False,
        description="True if another prediction already claimed this ground-truth defect",
    )
    explanation: str = Field(
        default="",
        description="Detailed notes on why the match succeeded or failed",
    )
