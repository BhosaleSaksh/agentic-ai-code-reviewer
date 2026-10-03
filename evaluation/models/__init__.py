"""Evaluation domain schemas and result models."""

from evaluation.models.case import (
    CaseProvenance,
    DefectCategory,
    EvaluationCase,
    ExpectedEvidence,
    ExpectedSeverity,
    GroundTruthDefect,
)
from evaluation.models.finding import MatchResult, NormalizedFinding
from evaluation.models.metrics import (
    BenchmarkMetrics,
    ConfusionMatrix,
    ResourceUsage,
    VerificationMetrics,
)
from evaluation.models.result import BenchmarkRunResult, CaseEvaluationResult

__all__ = [
    "BenchmarkMetrics",
    "BenchmarkRunResult",
    "CaseEvaluationResult",
    "CaseProvenance",
    "ConfusionMatrix",
    "DefectCategory",
    "EvaluationCase",
    "ExpectedEvidence",
    "ExpectedSeverity",
    "GroundTruthDefect",
    "MatchResult",
    "NormalizedFinding",
    "ResourceUsage",
    "VerificationMetrics",
]
