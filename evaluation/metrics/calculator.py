"""Metrics calculator computing precision, recall, F1, error rates, and confidence intervals."""

from __future__ import annotations

import math

from evaluation.models.metrics import (
    BenchmarkMetrics,
    ConfusionMatrix,
    VerificationMetrics,
)


class MetricsCalculator:
    """Computes deterministic empirical quality metrics for code review evaluation."""

    @staticmethod
    def wilson_score_interval(
        successes: int, total: int, confidence: float = 0.95
    ) -> tuple[float, float]:
        """Compute Wilson score confidence interval for binomial proportions.

        Args:
            successes: Number of successful trials (e.g. TP)
            total: Total number of trials (e.g. TP + FP)
            confidence: Confidence level (default 0.95 -> z ~ 1.96)

        Returns:
            tuple[float, float]: (lower_bound, upper_bound) in range [0.0, 1.0]
        """
        if total <= 0:
            return (0.0, 0.0)

        # Standard normal quantiles: 0.90 -> 1.645, 0.95 -> 1.96, 0.99 -> 2.576
        z = 1.95996 if math.isclose(confidence, 0.95) else 1.96
        p = successes / total
        denominator = 1.0 + (z**2) / total
        center = (p + (z**2) / (2.0 * total)) / denominator
        spread = (
            z * math.sqrt((p * (1.0 - p) + (z**2) / (4.0 * total)) / total)
        ) / denominator

        lower = max(0.0, round(center - spread, 4))
        upper = min(1.0, round(center + spread, 4))
        return (lower, upper)

    @classmethod
    def calculate_metrics(
        cls,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
        true_negatives: int = 0,
    ) -> BenchmarkMetrics:
        """Calculate complete benchmark metrics suite deterministically."""
        tp = max(0, true_positives)
        fp = max(0, false_positives)
        fn = max(0, false_negatives)
        tn = max(0, true_negatives)

        # Precision = TP / (TP + FP)
        predicted_total = tp + fp
        precision = round(tp / predicted_total, 4) if predicted_total > 0 else 0.0

        # Recall = TP / (TP + FN)
        actual_total = tp + fn
        recall = round(tp / actual_total, 4) if actual_total > 0 else 0.0

        # F1 = 2 * (P * R) / (P + R)
        if precision + recall > 0:
            f1 = round(2.0 * (precision * recall) / (precision + recall), 4)
        else:
            f1 = 0.0

        # False Discovery / Positive Rate: FP / (FP + TN) if TN > 0 else FP / (TP + FP)
        if tn > 0:
            fpr = round(fp / (fp + tn), 4)
        elif predicted_total > 0:
            fpr = round(fp / predicted_total, 4)
        else:
            fpr = 0.0

        # False Negative Rate: FN / (TP + FN)
        fnr = round(fn / actual_total, 4) if actual_total > 0 else 0.0

        # Defect Detection Rate: TP / Total Defects
        detection_rate = recall

        precision_ci = cls.wilson_score_interval(tp, predicted_total)
        recall_ci = cls.wilson_score_interval(tp, actual_total)

        return BenchmarkMetrics(
            true_positives=tp,
            false_positives=fp,
            true_negatives=tn,
            false_negatives=fn,
            precision=precision,
            recall=recall,
            f1_score=f1,
            false_positive_rate=fpr,
            false_negative_rate=fnr,
            defect_detection_rate=detection_rate,
            precision_ci=precision_ci,
            recall_ci=recall_ci,
        )

    @classmethod
    def calculate_from_confusion_matrix(cls, cm: ConfusionMatrix) -> BenchmarkMetrics:
        """Calculate metrics directly from a ConfusionMatrix instance."""
        return cls.calculate_metrics(
            true_positives=cm.true_positives,
            false_positives=cm.false_positives,
            false_negatives=cm.false_negatives,
            true_negatives=cm.true_negatives,
        )

    @staticmethod
    def calculate_verification_metrics(
        total_candidates: int,
        verified_count: int,
        rejected_count: int,
        evidence_grounded_count: int,
    ) -> VerificationMetrics:
        """Compute verification and grounding rates."""
        cand = max(0, total_candidates)
        ver = max(0, verified_count)
        rej = max(0, rejected_count)
        ev = max(0, evidence_grounded_count)

        verified_rate = round(ver / cand, 4) if cand > 0 else 0.0
        rejected_rate = round(rej / cand, 4) if cand > 0 else 0.0
        grounded_rate = (
            round(ev / ver, 4)
            if ver > 0
            else (round(ev / cand, 4) if cand > 0 else 0.0)
        )
        critic_rejection_rate = rejected_rate

        return VerificationMetrics(
            total_candidates=cand,
            verified_count=ver,
            rejected_count=rej,
            verified_rate=verified_rate,
            rejected_rate=rejected_rate,
            evidence_grounded_count=ev,
            evidence_grounded_rate=grounded_rate,
            critic_rejection_rate=critic_rejection_rate,
        )
