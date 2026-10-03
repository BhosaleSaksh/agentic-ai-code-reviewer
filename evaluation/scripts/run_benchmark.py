"""CLI script executing code review evaluation benchmarks and producing metrics reports."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

# Add project root to sys.path so imports work smoothly
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evaluation.baselines.ablation import (  # noqa: E402
    AgenticNoCriticBaseline,
    AgenticNoStaticEvidenceBaseline,
)
from evaluation.baselines.agentic import AgenticReviewerBaseline  # noqa: E402
from evaluation.baselines.base import BaseBaseline  # noqa: E402
from evaluation.baselines.single_llm import SingleLLMBaseline  # noqa: E402
from evaluation.baselines.static_analysis import StaticAnalysisBaseline  # noqa: E402
from evaluation.runner import BenchmarkRunner  # noqa: E402


def format_metrics_table(results_list: list[Any]) -> str:
    """Format benchmark results into a clean markdown comparative table."""
    headers = [
        "Baseline",
        "Cases",
        "TP",
        "FP",
        "FN",
        "Precision",
        "Recall",
        "F1",
        "FPR",
        "FNR",
        "Latency(s)",
        "Grounded%",
    ]
    rows = []
    for r in results_list:
        m = r.overall_metrics
        u = r.total_resource_usage
        v = r.verification_metrics
        rows.append(
            [
                r.baseline_name,
                str(r.total_cases),
                str(m.true_positives),
                str(m.false_positives),
                str(m.false_negatives),
                f"{m.precision:.2f}",
                f"{m.recall:.2f}",
                f"{m.f1_score:.2f}",
                f"{m.false_positive_rate:.2f}",
                f"{m.false_negative_rate:.2f}",
                f"{u.latency_seconds:.2f}",
                f"{v.evidence_grounded_rate * 100:.1f}%",
            ]
        )

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    header_line = (
        "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    )
    separator_line = (
        "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    )
    data_lines = [
        "| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |"
        for row in rows
    ]

    return "\n".join([header_line, separator_line] + data_lines)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute empirical code review benchmarks across architectures."
    )
    parser.add_argument(
        "--baseline",
        choices=[
            "agentic",
            "single_llm",
            "static_only",
            "ablation_no_critic",
            "ablation_no_static",
            "all",
        ],
        default="all",
        help="Reviewer baseline or ablation to evaluate (default: all)",
    )
    parser.add_argument(
        "--category",
        choices=["security", "bug_logic", "error_handling", "test_adequacy", "all"],
        default="all",
        help="Sub-category of synthetic cases to evaluate (default: all)",
    )
    parser.add_argument(
        "--dataset-dir",
        default="evaluation/datasets",
        help="Path to datasets directory",
    )
    parser.add_argument(
        "--results-dir",
        default="evaluation/results",
        help="Path to save evaluation output results",
    )

    args = parser.parse_args()

    runner = BenchmarkRunner(
        dataset_dir=args.dataset_dir,
        results_dir=args.results_dir,
    )

    category_subdir = None if args.category == "all" else args.category
    cases = runner.load_cases_from_directory(category_subdir=category_subdir)

    if not cases:
        print(
            f"No evaluation cases discovered in {args.dataset_dir}/synthetic/{category_subdir or ''}"
        )
        sys.exit(1)

    print(
        f"Loaded {len(cases)} benchmark cases from {args.dataset_dir}/synthetic (filter={args.category})"
    )

    baseline_registry: dict[str, BaseBaseline] = {
        "static_only": StaticAnalysisBaseline(),
        "single_llm": SingleLLMBaseline(),
        "agentic": AgenticReviewerBaseline(),
        "ablation_no_critic": AgenticNoCriticBaseline(),
        "ablation_no_static": AgenticNoStaticEvidenceBaseline(),
    }

    selected_baselines: list[BaseBaseline] = []
    if args.baseline == "all":
        selected_baselines = [
            baseline_registry["static_only"],
            baseline_registry["single_llm"],
            baseline_registry["ablation_no_static"],
            baseline_registry["ablation_no_critic"],
            baseline_registry["agentic"],
        ]
    else:
        selected_baselines = [baseline_registry[args.baseline]]

    results = []
    for bl in selected_baselines:
        print(f"Executing baseline [{bl.name}] against {len(cases)} cases...")
        res = await runner.run_benchmark(
            baseline=bl,
            cases=cases,
            metadata={"category_filter": args.category},
        )
        results.append(res)
        print(
            f"  -> Done! TP={res.overall_metrics.true_positives} "
            f"FP={res.overall_metrics.false_positives} "
            f"FN={res.overall_metrics.false_negatives} "
            f"Precision={res.overall_metrics.precision:.2f} "
            f"Recall={res.overall_metrics.recall:.2f} "
            f"F1={res.overall_metrics.f1_score:.2f}"
        )

    print("\n" + "=" * 80)
    print("BENCHMARK COMPARATIVE EVALUATION SUMMARY")
    print("=" * 80)
    print(format_metrics_table(results))
    print(f"\nArtifact reports saved to: {args.results_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
