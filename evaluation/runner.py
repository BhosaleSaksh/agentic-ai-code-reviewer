"""Benchmark runner orchestrating case loading, baseline execution, matching, and result serialization."""

from __future__ import annotations

import csv
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.baselines.base import BaseBaseline
from evaluation.matching.matcher import DeterministicFindingMatcher
from evaluation.metrics.calculator import MetricsCalculator
from evaluation.models.case import EvaluationCase
from evaluation.models.metrics import (
    BenchmarkMetrics,
    ResourceUsage,
)
from evaluation.models.result import BenchmarkRunResult, CaseEvaluationResult

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Orchestrates reproducible evaluation runs comparing reviewer baselines."""

    def __init__(
        self,
        dataset_dir: str | Path | None = None,
        results_dir: str | Path | None = None,
        matcher: DeterministicFindingMatcher | None = None,
        git_commit_sha: str = "0272942fd8b9267d8e798efffca9b831cd04cda1",
    ) -> None:
        self.dataset_dir = (
            Path(dataset_dir) if dataset_dir else Path("evaluation/datasets")
        )
        self.results_dir = (
            Path(results_dir) if results_dir else Path("evaluation/results")
        )
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.matcher = matcher or DeterministicFindingMatcher()
        self.git_commit_sha = git_commit_sha

    def load_cases_from_directory(
        self, category_subdir: str | None = None
    ) -> list[EvaluationCase]:
        """Discover and load all JSON evaluation cases from the synthetic dataset directory."""
        cases: list[EvaluationCase] = []
        target_dir = self.dataset_dir / "synthetic"
        if category_subdir:
            target_dir = target_dir / category_subdir

        if not target_dir.exists():
            logger.warning("Dataset directory does not exist: %s", target_dir)
            return cases

        for json_file in sorted(target_dir.rglob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                # If file contains an evaluation case or manifest entry
                if "case_id" in data and "ground_truth" in data:
                    cases.append(EvaluationCase.model_validate(data))
            except Exception as e:
                logger.error("Failed to load evaluation case from %s: %s", json_file, e)

        return cases

    def load_case_from_dict(self, data: dict[str, Any]) -> EvaluationCase:
        """Parse an in-memory dictionary into an EvaluationCase."""
        return EvaluationCase.model_validate(data)

    async def run_benchmark(
        self,
        baseline: BaseBaseline,
        cases: list[EvaluationCase],
        dataset_version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
    ) -> BenchmarkRunResult:
        """Execute a baseline across all benchmark cases and produce an aggregated report."""
        run_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).isoformat()

        case_results: list[CaseEvaluationResult] = []
        total_tp = 0
        total_fp = 0
        total_fn = 0
        total_candidates = 0
        total_verified = 0
        total_rejected = 0
        total_grounded = 0

        total_latency = 0.0
        total_api_calls = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0

        category_counts: dict[str, dict[str, int]] = {}

        for case in cases:
            # 1. Execute baseline
            predicted_findings, usage = await baseline.evaluate_case(case)

            total_latency += usage.latency_seconds
            total_api_calls += usage.api_calls
            total_prompt_tokens += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens
            total_cost += usage.estimated_cost_usd

            # 2. Match predicted findings against ground truth
            match_results, unmatched_gt, unmatched_preds = self.matcher.match(
                predicted_findings=predicted_findings,
                ground_truth_defects=case.ground_truth,
            )

            # Categorize match outcomes
            tp = sum(1 for m in match_results if m.matched and not m.is_duplicate)
            duplicates = sum(1 for m in match_results if m.is_duplicate)
            fp = len(unmatched_preds) + duplicates
            fn = len(unmatched_gt)

            total_tp += tp
            total_fp += fp
            total_fn += fn

            # Verification accounting
            total_candidates += len(predicted_findings)
            for f in predicted_findings:
                if f.is_verified:
                    total_verified += 1
                    if len(f.evidence) > 0:
                        total_grounded += 1
                else:
                    total_rejected += 1

            # Category tracking
            cat_key = case.category.value
            if cat_key not in category_counts:
                category_counts[cat_key] = {"tp": 0, "fp": 0, "fn": 0}
            category_counts[cat_key]["tp"] += tp
            category_counts[cat_key]["fp"] += fp
            category_counts[cat_key]["fn"] += fn

            case_res = CaseEvaluationResult(
                case_id=case.case_id,
                category=case.category.value,
                ground_truth_count=len(case.ground_truth),
                predicted_count=len(predicted_findings),
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                duplicates=duplicates,
                matched_pairs=[m.model_dump() for m in match_results if m.matched],
                unmatched_predictions=[p.model_dump() for p in unmatched_preds],
                unmatched_ground_truth=[g.model_dump() for g in unmatched_gt],
                resource_usage=usage,
            )
            case_results.append(case_res)

        # 3. Compute aggregate metrics
        overall_metrics = MetricsCalculator.calculate_metrics(
            true_positives=total_tp,
            false_positives=total_fp,
            false_negatives=total_fn,
        )

        category_metrics: dict[str, BenchmarkMetrics] = {}
        for cat, counts in category_counts.items():
            category_metrics[cat] = MetricsCalculator.calculate_metrics(
                true_positives=counts["tp"],
                false_positives=counts["fp"],
                false_negatives=counts["fn"],
            )

        verification_metrics = MetricsCalculator.calculate_verification_metrics(
            total_candidates=total_candidates,
            verified_count=total_verified,
            rejected_count=total_rejected,
            evidence_grounded_count=total_grounded,
        )

        total_tokens = total_prompt_tokens + total_completion_tokens
        total_usage = ResourceUsage(
            latency_seconds=round(total_latency, 4),
            api_calls=total_api_calls,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(total_cost, 6),
        )

        run_result = BenchmarkRunResult(
            run_id=run_id,
            baseline_name=baseline.name,
            dataset_version=dataset_version,
            timestamp=timestamp,
            git_commit_sha=self.git_commit_sha,
            total_cases=len(cases),
            overall_metrics=overall_metrics,
            category_metrics=category_metrics,
            verification_metrics=verification_metrics,
            total_resource_usage=total_usage,
            case_results=case_results,
            execution_metadata=metadata or {},
        )

        # 4. Serialize results
        self.serialize_results(run_result)

        return run_result

    def serialize_results(self, result: BenchmarkRunResult) -> tuple[Path, Path]:
        """Save machine-readable JSON and CSV summaries in results directory."""
        json_path = self.results_dir / f"{result.run_id}_{result.baseline_name}.json"
        csv_path = (
            self.results_dir / f"{result.run_id}_{result.baseline_name}_summary.csv"
        )

        # Write JSON report
        json_path.write_text(
            json.dumps(result.model_dump(), indent=2), encoding="utf-8"
        )

        # Write CSV report summary
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "run_id",
                    "baseline_name",
                    "dataset_version",
                    "total_cases",
                    "true_positives",
                    "false_positives",
                    "false_negatives",
                    "precision",
                    "recall",
                    "f1_score",
                    "false_positive_rate",
                    "false_negative_rate",
                    "latency_seconds",
                    "total_tokens",
                    "cost_usd",
                    "evidence_grounded_rate",
                    "git_commit_sha",
                ]
            )
            writer.writerow(
                [
                    result.run_id,
                    result.baseline_name,
                    result.dataset_version,
                    result.total_cases,
                    result.overall_metrics.true_positives,
                    result.overall_metrics.false_positives,
                    result.overall_metrics.false_negatives,
                    result.overall_metrics.precision,
                    result.overall_metrics.recall,
                    result.overall_metrics.f1_score,
                    result.overall_metrics.false_positive_rate,
                    result.overall_metrics.false_negative_rate,
                    result.total_resource_usage.latency_seconds,
                    result.total_resource_usage.total_tokens,
                    result.total_resource_usage.estimated_cost_usd,
                    result.verification_metrics.evidence_grounded_rate,
                    result.git_commit_sha,
                ]
            )

        logger.info("Evaluation results serialized to %s and %s", json_path, csv_path)
        return json_path, csv_path
