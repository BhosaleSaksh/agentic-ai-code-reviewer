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
from evaluation.matching.evidence_auditor import EvidenceAuditor
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
        git_commit_sha: str = "af0f0427252487b6cd0b76bba14a0d611fd67024",
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

    def load_all_cases(
        self,
        include_real_world: bool = True,
        category: str | None = None,
    ) -> list[EvaluationCase]:
        """Discover and load all JSON evaluation cases from synthetic and real-world directories."""
        cases: list[EvaluationCase] = []

        # 1. Load synthetic cases (18 total)
        synth_dir = self.dataset_dir / "synthetic"
        if synth_dir.exists():
            for json_file in sorted(synth_dir.rglob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if "case_id" in data and "ground_truth" in data:
                        case = EvaluationCase.model_validate(data)
                        if not category or case.category.value == category:
                            cases.append(case)
                except Exception as e:
                    logger.error(
                        "Failed to load synthetic case from %s: %s", json_file, e
                    )

        # 2. Load real-world cases (5 total)
        if include_real_world:
            rw_dir = self.dataset_dir / "real_world"
            if rw_dir.exists():
                for json_file in sorted(rw_dir.glob("*.json")):
                    try:
                        data = json.loads(json_file.read_text(encoding="utf-8"))
                        if "case_id" in data and "ground_truth" in data:
                            case = EvaluationCase.model_validate(data)
                            if not category or case.category.value == category:
                                cases.append(case)
                    except Exception as e:
                        logger.error(
                            "Failed to load real-world case from %s: %s",
                            json_file,
                            e,
                        )

        return cases

    def load_cases_from_directory(
        self, category_subdir: str | None = None
    ) -> list[EvaluationCase]:
        """Backward-compatible loader for synthetic cases."""
        return self.load_all_cases(include_real_world=False, category=category_subdir)

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
            # Strictly isolate model input context to prevent ground-truth leakage
            eval_input = case.to_evaluation_input()

            # 1. Execute baseline
            predicted_findings, usage = await baseline.evaluate_case(eval_input)

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

            # Verification and evidence-grounding audit
            total_candidates += len(predicted_findings)
            for f in predicted_findings:
                if f.is_verified:
                    total_verified += 1
                    # Rigorous evidence audit verifying non-empty snippet, valid tool, and file/line bounds
                    if EvidenceAuditor.is_finding_grounded(f, eval_input):
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
            execution_mode=getattr(baseline, "execution_mode", "offline_mock"),
            provider=getattr(baseline, "provider_name", "offline_simulator"),
            model=getattr(baseline, "model_name", "deterministic_mock"),
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
        self.serialize_results(run_result, baseline)

        return run_result

    def serialize_results(
        self, result: BenchmarkRunResult, _baseline: BaseBaseline | None = None
    ) -> tuple[Path, Path]:
        """Save run artifacts in isolated directory evaluation/results/<run_id>/ and legacy paths."""
        # 1. Isolated run directory (Part 14)
        run_dir = self.results_dir / result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        config_file = run_dir / "config.json"
        summary_file = run_dir / "summary.json"
        cases_file = run_dir / "cases.json"
        metrics_file = run_dir / "metrics.csv"

        config_data = {
            "run_id": result.run_id,
            "baseline_name": result.baseline_name,
            "execution_mode": result.execution_mode,
            "provider": result.provider,
            "model": result.model,
            "dataset_version": result.dataset_version,
            "git_commit_sha": result.git_commit_sha,
            "timestamp": result.timestamp,
            "total_cases": result.total_cases,
            "execution_metadata": result.execution_metadata,
        }
        config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

        summary_file.write_text(
            json.dumps(result.model_dump(), indent=2), encoding="utf-8"
        )

        cases_data = [c.model_dump() for c in result.case_results]
        cases_file.write_text(json.dumps(cases_data, indent=2), encoding="utf-8")

        with open(metrics_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "category",
                    "cases",
                    "tp",
                    "fp",
                    "fn",
                    "precision",
                    "recall",
                    "f1",
                    "fpr",
                    "fnr",
                    "ddr",
                ]
            )
            ov = result.overall_metrics
            writer.writerow(
                [
                    "OVERALL",
                    result.total_cases,
                    ov.true_positives,
                    ov.false_positives,
                    ov.false_negatives,
                    ov.precision,
                    ov.recall,
                    ov.f1_score,
                    ov.false_positive_rate,
                    ov.false_negative_rate,
                    ov.defect_detection_rate,
                ]
            )
            for cat, cm in result.category_metrics.items():
                writer.writerow(
                    [
                        cat,
                        "-",
                        cm.true_positives,
                        cm.false_positives,
                        cm.false_negatives,
                        cm.precision,
                        cm.recall,
                        cm.f1_score,
                        cm.false_positive_rate,
                        cm.false_negative_rate,
                        cm.defect_detection_rate,
                    ]
                )

        # 2. Legacy root files in results_dir for backwards compatibility
        legacy_json_path = (
            self.results_dir / f"{result.run_id}_{result.baseline_name}.json"
        )
        legacy_csv_path = (
            self.results_dir / f"{result.run_id}_{result.baseline_name}_summary.csv"
        )

        legacy_json_path.write_text(
            json.dumps(result.model_dump(), indent=2), encoding="utf-8"
        )

        with open(legacy_csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "run_id",
                    "baseline_name",
                    "execution_mode",
                    "provider",
                    "model",
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
                    result.execution_mode,
                    result.provider,
                    result.model,
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

        logger.info(
            "Evaluation results serialized to directory %s and legacy files %s, %s",
            run_dir,
            legacy_json_path,
            legacy_csv_path,
        )
        return legacy_json_path, legacy_csv_path
