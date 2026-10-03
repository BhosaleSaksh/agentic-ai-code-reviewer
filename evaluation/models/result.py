"""Benchmark run outcome and case-level evaluation results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evaluation.models.metrics import (
    BenchmarkMetrics,
    ResourceUsage,
    VerificationMetrics,
)


class CaseEvaluationResult(BaseModel):
    """Evaluation evaluation record for an individual benchmark case."""

    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(description="Evaluation case identifier")
    category: str = Field(description="Category of the evaluated case")
    ground_truth_count: int = Field(
        ge=0, description="Number of expected ground truth defects"
    )
    predicted_count: int = Field(
        ge=0, description="Total findings predicted by reviewer"
    )
    true_positives: int = Field(
        ge=0, description="Number of correctly matched findings"
    )
    false_positives: int = Field(
        ge=0, description="Number of spurious or incorrect predictions"
    )
    false_negatives: int = Field(
        ge=0, description="Number of missed ground truth defects"
    )
    duplicates: int = Field(
        ge=0, description="Redundant predictions for already-matched defects"
    )

    matched_pairs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed record of each successful match",
    )
    unmatched_predictions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of predicted findings that did not match ground truth",
    )
    unmatched_ground_truth: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of ground-truth defects that were not detected",
    )
    resource_usage: ResourceUsage = Field(
        default_factory=ResourceUsage,
        description="Compute and token resource usage for this case",
    )


class BenchmarkRunResult(BaseModel):
    """Aggregate reproducible evaluation report for a complete benchmark execution."""

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(description="UUID v4 identifying this specific benchmark run")
    baseline_name: str = Field(description="Name of the evaluated baseline or ablation")
    execution_mode: str = Field(
        default="offline_mock",
        description="Explicit execution mode: offline_mock or real_llm",
    )
    provider: str = Field(
        default="offline_simulator",
        description="LLM provider name or offline simulator",
    )
    model: str = Field(
        default="deterministic_mock",
        description="Model identifier or heuristic version",
    )
    dataset_version: str = Field(description="Dataset version identifier (e.g. 1.0.0)")
    timestamp: str = Field(description="ISO-8601 UTC timestamp of execution")
    git_commit_sha: str = Field(description="Repository Git commit SHA at time of run")

    total_cases: int = Field(ge=0, description="Total benchmark cases processed")
    overall_metrics: BenchmarkMetrics = Field(
        description="Aggregated precision, recall, F1, and error rates across all cases"
    )
    category_metrics: dict[str, BenchmarkMetrics] = Field(
        default_factory=dict,
        description="Breakdown of benchmark metrics per defect category",
    )
    verification_metrics: VerificationMetrics = Field(
        default_factory=VerificationMetrics,
        description="Verification, rejection, and evidence grounding breakdown",
    )
    total_resource_usage: ResourceUsage = Field(
        default_factory=ResourceUsage,
        description="Summed compute latency, API calls, tokens, and cost",
    )
    case_results: list[CaseEvaluationResult] = Field(
        default_factory=list,
        description="Per-case evaluation details",
    )
    execution_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Model identifier, configuration flags, and system environment info",
    )
