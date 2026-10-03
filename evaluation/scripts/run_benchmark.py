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
        "Mode",
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
                r.execution_mode,
                str(r.total_cases),
                str(m.true_positives),
                str(m.false_positives),
                str(m.false_negatives),
                f"{m.precision:.2f}",
                f"{m.recall:.2f}",
                f"{m.f1_score:.2f}",
                f"{m.false_positive_rate:.2f}",
                f"{m.false_negative_rate:.2f}",
                f"{u.latency_seconds:.4f}",
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
            "agentic_critic_full",
            "single_llm_reviewer",
            "static_analysis_only",
            "all",
        ],
        default="all",
        help="Reviewer baseline or ablation to evaluate (default: all)",
    )
    parser.add_argument(
        "--category",
        choices=[
            "SECURITY",
            "BUG_LOGIC",
            "ERROR_HANDLING",
            "TEST_ADEQUACY",
            "security",
            "bug_logic",
            "error_handling",
            "test_adequacy",
            "all",
        ],
        default="all",
        help="Category filter (default: all)",
    )
    parser.add_argument(
        "--mode",
        choices=["offline", "real"],
        default="offline",
        help="Execution mode: offline (deterministic simulation) or real (live LLM API)",
    )
    parser.add_argument(
        "--include-real-world",
        action="store_true",
        default=True,
        help="Include real-world open-source PR benchmark cases (default: True)",
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        default=False,
        help="Run only synthetic benchmark cases, excluding real-world cases",
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

    include_real_world = args.include_real_world and not args.synthetic_only
    category_filter = None if args.category.lower() == "all" else args.category.upper()

    runner = BenchmarkRunner(
        dataset_dir=args.dataset_dir,
        results_dir=args.results_dir,
    )

    cases = runner.load_all_cases(
        include_real_world=include_real_world,
        category=category_filter,
    )

    if not cases:
        print(
            f"No evaluation cases discovered in {args.dataset_dir} (category={args.category})"
        )
        sys.exit(1)

    print("=" * 80)
    print(f"BENCHMARK RUN INITIALIZATION: MODE={args.mode.upper()}")
    print("=" * 80)
    print(
        f"Loaded {len(cases)} total cases (Synthetic + Real-World={include_real_world}, category={args.category})"
    )

    # Initialize baselines with explicit mode
    baseline_registry: dict[str, BaseBaseline] = {
        "static_only": StaticAnalysisBaseline(mode=args.mode),
        "static_analysis_only": StaticAnalysisBaseline(mode=args.mode),
        "single_llm": SingleLLMBaseline(mode=args.mode),
        "single_llm_reviewer": SingleLLMBaseline(mode=args.mode),
        "agentic": AgenticReviewerBaseline(mode=args.mode),
        "agentic_critic_full": AgenticReviewerBaseline(mode=args.mode),
        "ablation_no_critic": AgenticNoCriticBaseline(mode=args.mode),
        "ablation_no_static": AgenticNoStaticEvidenceBaseline(mode=args.mode),
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
        print(
            f"\nExecuting baseline [{bl.name}] (mode={bl.execution_mode}) across {len(cases)} cases..."
        )
        try:
            res = await runner.run_benchmark(
                baseline=bl,
                cases=cases,
                metadata={"category_filter": args.category, "mode": args.mode},
            )
            results.append(res)
            print(
                f"  -> Done! TP={res.overall_metrics.true_positives} "
                f"FP={res.overall_metrics.false_positives} "
                f"FN={res.overall_metrics.false_negatives} "
                f"Precision={res.overall_metrics.precision:.2f} "
                f"Recall={res.overall_metrics.recall:.2f} "
                f"F1={res.overall_metrics.f1_score:.2f} "
                f"Latency={res.total_resource_usage.latency_seconds:.4f}s"
            )
        except RuntimeError as exc:
            print(f"  -> ERROR executing {bl.name} in mode={args.mode}: {exc}")
            if args.mode == "real":
                print(
                    "     Aborting benchmark: real mode requires provisioned provider credentials."
                )
                sys.exit(1)

    print("\n" + "=" * 80)
    print("BENCHMARK COMPARATIVE EVALUATION SUMMARY")
    print("=" * 80)
    print(format_metrics_table(results))
    print(f"\nArtifact reports saved to: {args.results_dir}/<run_id>/")


if __name__ == "__main__":
    asyncio.run(main())
