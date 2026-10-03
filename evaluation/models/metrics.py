"""Benchmark evaluation metrics, resource usage telemetry, and verification statistics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConfusionMatrix(BaseModel):
    """Confusion matrix counts for detection evaluation."""

    model_config = ConfigDict(extra="ignore")

    true_positives: int = Field(
        ge=0, description="Correctly identified ground-truth defects"
    )
    false_positives: int = Field(
        ge=0, description="Predicted findings not in ground truth"
    )
    true_negatives: int = Field(
        ge=0, description="Correctly withheld non-defects (where defined)"
    )
    false_negatives: int = Field(ge=0, description="Missed ground-truth defects")


class BenchmarkMetrics(BaseModel):
    """Standard statistical metrics computed for a benchmark run."""

    model_config = ConfigDict(extra="ignore")

    true_positives: int = Field(ge=0, description="Count of true positives")
    false_positives: int = Field(ge=0, description="Count of false positives")
    true_negatives: int = Field(ge=0, description="Count of true negatives")
    false_negatives: int = Field(ge=0, description="Count of false negatives")

    precision: float = Field(
        ge=0.0,
        le=1.0,
        description="TP / (TP + FP) or 0.0 if denominator is 0",
    )
    recall: float = Field(
        ge=0.0,
        le=1.0,
        description="TP / (TP + FN) or 0.0 if denominator is 0",
    )
    f1_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Harmonic mean of precision and recall",
    )
    false_positive_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="FP / (FP + TN) or FP / Total Predictions",
    )
    false_negative_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="FN / (TP + FN)",
    )
    defect_detection_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="TP / Total Ground Truth Defects",
    )

    precision_ci: tuple[float, float] = Field(
        default=(0.0, 0.0),
        description="Wilson score 95% confidence interval for precision",
    )
    recall_ci: tuple[float, float] = Field(
        default=(0.0, 0.0),
        description="Wilson score 95% confidence interval for recall",
    )


class ResourceUsage(BaseModel):
    """Execution telemetry tracking compute time, token volumes, and estimated cost."""

    model_config = ConfigDict(extra="ignore")

    latency_seconds: float = Field(
        ge=0.0,
        default=0.0,
        description="Total wall-clock duration of the evaluation in seconds",
    )
    api_calls: int = Field(
        ge=0,
        default=0,
        description="Number of external LLM API calls executed",
    )
    prompt_tokens: int = Field(
        ge=0,
        default=0,
        description="Total prompt tokens consumed",
    )
    completion_tokens: int = Field(
        ge=0,
        default=0,
        description="Total completion tokens generated",
    )
    total_tokens: int = Field(
        ge=0,
        default=0,
        description="Total token usage across all calls",
    )
    estimated_cost_usd: float = Field(
        ge=0.0,
        default=0.0,
        description="Estimated API cost in US Dollars based on standard pricing",
    )


class VerificationMetrics(BaseModel):
    """Metrics tracking the effect of evidence grounding and critic verification."""

    model_config = ConfigDict(extra="ignore")

    total_candidates: int = Field(
        ge=0,
        default=0,
        description="Total candidate findings produced by specialists before critic",
    )
    verified_count: int = Field(
        ge=0,
        default=0,
        description="Candidate findings confirmed as verified",
    )
    rejected_count: int = Field(
        ge=0,
        default=0,
        description="Candidate findings rejected as false alarms by critic",
    )
    verified_rate: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="verified_count / total_candidates",
    )
    rejected_rate: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="rejected_count / total_candidates",
    )
    evidence_grounded_count: int = Field(
        ge=0,
        default=0,
        description="Findings backed by at least one valid evidence reference",
    )
    evidence_grounded_rate: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="evidence_grounded_count / total_verified_findings",
    )
    critic_rejection_rate: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="Proportion of candidate findings suppressed by the critic",
    )
