"""Deterministic finding matching layer for benchmark evaluation.

Pairs predicted findings with ground-truth defect specifications based on:
1. Normalized file path identity
2. Line coordinate proximity / interval tolerance
3. Issue category and semantic defect compatibility
4. Strict one-to-one assignment policy with duplicate penalization
"""

from __future__ import annotations

import os
from typing import Any

from evaluation.models.case import GroundTruthDefect
from evaluation.models.finding import MatchResult, NormalizedFinding


class DeterministicFindingMatcher:
    """Evaluates predicted reviewer findings against authoritative ground truth."""

    def __init__(self, line_tolerance: int = 5) -> None:
        """Initialize matcher with coordinate proximity tolerance.

        Args:
            line_tolerance: Maximum allowable distance in lines between predicted
                line range and ground-truth boundary.
        """
        self.line_tolerance = max(0, line_tolerance)

    @staticmethod
    def normalize_path(path: str) -> str:
        """Standardize file paths across platforms and diff prefixes."""
        normalized = path.replace("\\", "/").strip()
        for prefix in ("a/", "b/", "./", "/"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
        return os.path.normpath(normalized).replace("\\", "/")

    @classmethod
    def paths_match(cls, path_a: str, path_b: str) -> bool:
        """Check whether two file paths refer to the same source module."""
        norm_a = cls.normalize_path(path_a)
        norm_b = cls.normalize_path(path_b)
        return (
            norm_a == norm_b
            or norm_a.endswith("/" + norm_b)
            or norm_b.endswith("/" + norm_a)
        )

    @classmethod
    def calculate_line_distance(
        cls,
        pred_start: int,
        pred_end: int,
        gt_start: int,
        gt_end: int,
    ) -> int:
        """Calculate line offset between two intervals (0 if overlapping)."""
        if max(pred_start, gt_start) <= min(pred_end, gt_end):
            return 0
        if pred_end < gt_start:
            return gt_start - pred_end
        return pred_start - gt_end

    @classmethod
    def categories_compatible(cls, predicted_category: str, gt_category: str) -> bool:
        """Determine whether the predicted category matches ground truth expectation."""
        p = predicted_category.upper().replace("-", "_").replace(" ", "_")
        g = gt_category.upper().replace("-", "_").replace(" ", "_")

        if p == g:
            return True

        # Category alias mappings
        synonyms = {
            "SECURITY": {"SECURITY", "VULNERABILITY", "CVE", "INJECTION", "AUTH"},
            "BUG_LOGIC": {
                "BUG_LOGIC",
                "CORRECTNESS",
                "LOGIC",
                "BOUNDARY",
                "CALCULATION",
                "STATE",
            },
            "ERROR_HANDLING": {
                "ERROR_HANDLING",
                "EXCEPTION",
                "ROBUSTNESS",
                "RESOURCE_LEAK",
            },
            "TEST_ADEQUACY": {
                "TEST_ADEQUACY",
                "TESTING",
                "TEST_COVERAGE",
                "REGRESSION_RISK",
            },
        }

        for std_cat, alias_set in synonyms.items():
            if (p in alias_set or std_cat in p) and (g in alias_set or std_cat in g):
                return True

        return False

    def match(
        self,
        predicted_findings: list[NormalizedFinding],
        ground_truth_defects: list[GroundTruthDefect],
    ) -> tuple[list[MatchResult], list[GroundTruthDefect], list[NormalizedFinding]]:
        """Pair predicted findings to ground truth using greedy bipartite assignment.

        Returns:
            tuple containing:
                - List of MatchResult objects for all predicted findings
                - List of unmatched GroundTruthDefect instances (False Negatives)
                - List of unmatched NormalizedFinding instances (False Positives)
        """
        # Formulate candidate match pairs with compatibility scores
        candidate_pairs: list[dict[str, Any]] = []

        for p_idx, pred in enumerate(predicted_findings):
            for gt_idx, gt in enumerate(ground_truth_defects):
                file_matched = self.paths_match(pred.affected_file, gt.affected_file)
                if not file_matched:
                    continue

                dist = self.calculate_line_distance(
                    pred.line_start, pred.line_end, gt.line_start, gt.line_end
                )
                if dist > self.line_tolerance:
                    continue

                cat_matched = self.categories_compatible(
                    pred.category, gt.category.value
                )

                # Compute match score (higher is better)
                line_score = 1.0 - (dist / (self.line_tolerance + 1.0)) * 0.4
                cat_score = 0.4 if cat_matched else 0.0

                # Keyword semantic bonus if expected issue type or explanation overlaps
                semantic_overlap = 0.0
                pred_text = f"{pred.title} {pred.explanation}".lower()
                gt_keywords = gt.expected_issue_type.lower().replace("_", " ").split()
                if any(kw in pred_text for kw in gt_keywords if len(kw) > 3):
                    semantic_overlap += 0.2

                total_score = line_score + cat_score + semantic_overlap

                candidate_pairs.append(
                    {
                        "score": total_score,
                        "pred_idx": p_idx,
                        "gt_idx": gt_idx,
                        "file_matched": file_matched,
                        "distance": dist,
                        "cat_matched": cat_matched,
                        "pred": pred,
                        "gt": gt,
                    }
                )

        # Sort candidate pairs descending by score
        candidate_pairs.sort(key=lambda x: x["score"], reverse=True)

        assigned_preds: set[int] = set()
        claimed_gt: set[int] = set()
        results: list[MatchResult] = []

        # First pass: assign best 1-to-1 matches
        for pair in candidate_pairs:
            p_idx = pair["pred_idx"]
            gt_idx = pair["gt_idx"]

            if p_idx in assigned_preds:
                continue

            if gt_idx not in claimed_gt:
                # Valid True Positive match
                claimed_gt.add(gt_idx)
                assigned_preds.add(p_idx)
                results.append(
                    MatchResult(
                        matched=True,
                        ground_truth_id=pair["gt"].defect_id,
                        predicted_finding_id=pair["pred"].finding_id,
                        file_matched=True,
                        line_distance=pair["distance"],
                        category_matched=pair["cat_matched"],
                        semantic_score=round(pair["score"] / 1.6, 3),
                        is_duplicate=False,
                        explanation=(
                            f"Matched {pair['gt'].defect_id} at lines "
                            f"{pair['pred'].line_start}-{pair['pred'].line_end} "
                            f"(distance={pair['distance']})"
                        ),
                    )
                )

        # Second pass: check remaining pairs for duplicate claims on already-matched GT
        for pair in candidate_pairs:
            p_idx = pair["pred_idx"]
            gt_idx = pair["gt_idx"]

            if p_idx in assigned_preds:
                continue

            if gt_idx in claimed_gt:
                # Redundant prediction for an already-matched defect
                assigned_preds.add(p_idx)
                results.append(
                    MatchResult(
                        matched=False,
                        ground_truth_id=pair["gt"].defect_id,
                        predicted_finding_id=pair["pred"].finding_id,
                        file_matched=True,
                        line_distance=pair["distance"],
                        category_matched=pair["cat_matched"],
                        semantic_score=round(pair["score"] / 1.6, 3),
                        is_duplicate=True,
                        explanation=(
                            f"Redundant prediction on {pair['gt'].defect_id}; "
                            f"defect was already matched by another finding."
                        ),
                    )
                )

        # Third pass: remaining predictions are unmatched False Positives
        unmatched_predictions: list[NormalizedFinding] = []
        for p_idx, pred in enumerate(predicted_findings):
            if p_idx not in assigned_preds:
                unmatched_predictions.append(pred)
                results.append(
                    MatchResult(
                        matched=False,
                        ground_truth_id=None,
                        predicted_finding_id=pred.finding_id,
                        file_matched=False,
                        line_distance=-1,
                        category_matched=False,
                        semantic_score=0.0,
                        is_duplicate=False,
                        explanation="Spurious finding: does not correspond to any ground-truth defect.",
                    )
                )

        # Identify unmatched ground truth (False Negatives)
        unmatched_ground_truth: list[GroundTruthDefect] = [
            gt for idx, gt in enumerate(ground_truth_defects) if idx not in claimed_gt
        ]

        return results, unmatched_ground_truth, unmatched_predictions
