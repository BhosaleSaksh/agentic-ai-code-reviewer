"""Unit and integration tests for the Phase 7 evaluation and benchmarking framework.

Validates:
1. Dataset manifest integrity and schema compliance
2. Evaluation case schema and ground-truth isolation (leakage prevention)
3. Deterministic finding matching with line tolerance and duplicate handling
4. Metric calculations (Precision, Recall, F1, FPR, FNR, Wilson score CIs)
5. Reviewer baselines (Static analysis, Single-LLM, Full Agentic, Ablations)
6. Benchmark execution runner and result serialization
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.baselines.ablation import (
    AgenticNoCriticBaseline,
)
from evaluation.baselines.agentic import AgenticReviewerBaseline
from evaluation.baselines.static_analysis import StaticAnalysisBaseline
from evaluation.matching.matcher import DeterministicFindingMatcher
from evaluation.metrics.calculator import MetricsCalculator
from evaluation.models.case import (
    CaseProvenance,
    DefectCategory,
    EvaluationCase,
    ExpectedSeverity,
    GroundTruthDefect,
)
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ConfusionMatrix
from evaluation.runner import BenchmarkRunner

DATASETS_DIR = Path("evaluation/datasets")


# ==============================================================================
# 1. Dataset Manifest & Schema Validation Tests
# ==============================================================================


def test_root_manifest_validation() -> None:
    """Validate root dataset manifest.json structure and references."""
    manifest_path = DATASETS_DIR / "manifest.json"
    assert manifest_path.exists(), (
        "Root manifest.json must exist in evaluation/datasets/"
    )

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["manifest_version"] == "1.0.0"
    assert "categories" in data
    assert len(data["categories"]) == 4

    synthetic_info = data["synthetic_corpus"]
    assert synthetic_info["total_cases"] == len(synthetic_info["case_ids"])

    # Verify every case ID listed in the manifest exists as a valid JSON file
    for case_id in synthetic_info["case_ids"]:
        matching_files = list(
            DATASETS_DIR.glob(f"synthetic/*/{case_id.lower().replace('-', '_')}.json")
        )
        assert len(matching_files) == 1, f"Missing case file for {case_id}"
        case_data = json.loads(matching_files[0].read_text(encoding="utf-8"))
        case = EvaluationCase.model_validate(case_data)
        assert case.case_id == case_id


def test_real_world_manifest_validation() -> None:
    """Validate real-world OSS PR benchmark manifest structure."""
    rw_path = DATASETS_DIR / "manifests" / "real_world_manifest.json"
    assert rw_path.exists(), "real_world_manifest.json must exist"

    data = json.loads(rw_path.read_text(encoding="utf-8"))
    assert "cases" in data
    assert len(data["cases"]) >= 5

    for case in data["cases"]:
        assert "case_id" in case
        assert "repository" in case
        assert "pr_number" in case
        assert "commit_sha" in case
        assert "ground_truth_authority" in case
        assert "annotation_uncertainty" in case
        assert case["annotation_uncertainty"] in {"LOW", "MEDIUM", "HIGH"}


def test_all_synthetic_cases_conform_to_schema() -> None:
    """Verify every synthetic case validates against Pydantic EvaluationCase schema."""
    case_files = list(DATASETS_DIR.glob("synthetic/*/*.json"))
    assert len(case_files) >= 18, (
        f"Expected at least 18 synthetic cases, found {len(case_files)}"
    )

    for file_path in case_files:
        content = json.loads(file_path.read_text(encoding="utf-8"))
        case = EvaluationCase.model_validate(content)

        assert case.case_id.startswith("SYNTH-")
        assert len(case.vulnerable_code) > 0
        assert len(case.ground_truth) >= 1

        for gt in case.ground_truth:
            assert gt.line_start <= gt.line_end
            assert gt.line_start >= 1
            assert len(gt.description) > 0
            assert len(gt.explanation) > 0
            assert gt.category in DefectCategory


# ==============================================================================
# 2. Leakage Prevention Isolation Tests
# ==============================================================================


def test_evaluation_case_leakage_isolation() -> None:
    """Verify to_evaluation_input strictly strips all ground-truth labels and descriptions."""
    case = EvaluationCase(
        case_id="SYNTH-SEC-TEST",
        category=DefectCategory.SECURITY,
        title="SQL Injection Vulnerability",
        description="Public description of the change",
        vulnerable_code="cursor.execute(f'SELECT * FROM users WHERE id = {user_id}')",
        affected_file="app/users.py",
        ground_truth=[
            GroundTruthDefect(
                defect_id="GT-001",
                category=DefectCategory.SECURITY,
                affected_file="app/users.py",
                line_start=1,
                line_end=1,
                expected_issue_type="SQL_INJECTION",
                expected_severity=ExpectedSeverity.HIGH,
                description="Confidential ground-truth description",
                explanation="Confidential ground-truth explanation",
            )
        ],
        provenance=CaseProvenance(
            source="synthetic",
            created_at="2026-10-03T00:00:00Z",
        ),
    )

    model_input = case.to_evaluation_input()

    assert "ground_truth" not in model_input
    assert "expected_issue_type" not in model_input
    assert "expected_severity" not in model_input
    assert "Confidential ground-truth" not in str(model_input)
    assert model_input["affected_file"] == "app/users.py"
    assert model_input["vulnerable_code"] == case.vulnerable_code


# ==============================================================================
# 3. Deterministic Finding Matcher Tests
# ==============================================================================


def test_matcher_exact_hit() -> None:
    """Matcher correctly pairs finding with identical file, line range, and category."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)

    gt = GroundTruthDefect(
        defect_id="GT-01",
        category=DefectCategory.SECURITY,
        affected_file="app/auth.py",
        line_start=10,
        line_end=12,
        expected_issue_type="SQL_INJECTION",
        expected_severity=ExpectedSeverity.HIGH,
        description="SQL injection vulnerability",
        explanation="Raw string interpolation",
    )

    pred = NormalizedFinding(
        finding_id="PRED-01",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/auth.py",
        line_start=10,
        line_end=12,
        title="SQL Injection Detected",
        explanation="User input directly interpolated into SQL cursor",
        confidence_score=0.95,
    )

    results, unmatched_gt, unmatched_pred = matcher.match([pred], [gt])

    assert len(results) == 1
    assert results[0].matched is True
    assert results[0].ground_truth_id == "GT-01"
    assert results[0].is_duplicate is False
    assert len(unmatched_gt) == 0
    assert len(unmatched_pred) == 0


def test_matcher_line_tolerance_boundary() -> None:
    """Matcher pairs finding within tolerance and rejects finding beyond tolerance."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)

    gt = GroundTruthDefect(
        defect_id="GT-01",
        category=DefectCategory.BUG_LOGIC,
        affected_file="app/utils.py",
        line_start=20,
        line_end=22,
        expected_issue_type="BOUNDARY_ERROR",
        description="Off by one",
        explanation="Boundary error",
    )

    # Within tolerance: line 25 is distance 3 from line 22 -> MATCH
    pred_near = NormalizedFinding(
        finding_id="PRED-NEAR",
        category="BUG_LOGIC",
        affected_file="app/utils.py",
        line_start=25,
        line_end=25,
        title="Boundary bug",
        explanation="Off by one error in loop",
    )

    results, unmatched_gt, unmatched_pred = matcher.match([pred_near], [gt])
    assert len(results) == 1
    assert results[0].matched is True
    assert results[0].line_distance == 3

    # Outside tolerance: line 40 is distance 18 from line 22 -> NO MATCH (FP + FN)
    pred_far = NormalizedFinding(
        finding_id="PRED-FAR",
        category="BUG_LOGIC",
        affected_file="app/utils.py",
        line_start=40,
        line_end=40,
        title="Boundary bug",
        explanation="Off by one error in loop",
    )

    results, unmatched_gt, unmatched_pred = matcher.match([pred_far], [gt])
    assert len(results) == 1
    assert results[0].matched is False
    assert len(unmatched_gt) == 1
    assert len(unmatched_pred) == 1


def test_matcher_duplicate_penalization() -> None:
    """When multiple findings target the same defect, only the first is TP; second is duplicate."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)

    gt = GroundTruthDefect(
        defect_id="GT-SINGLE",
        category=DefectCategory.SECURITY,
        affected_file="app/api.py",
        line_start=15,
        line_end=16,
        expected_issue_type="COMMAND_INJECTION",
        description="Subprocess shell=True",
        explanation="Command injection",
    )

    pred1 = NormalizedFinding(
        finding_id="PRED-A",
        category="SECURITY",
        affected_file="app/api.py",
        line_start=15,
        line_end=15,
        title="Command injection issue",
        explanation="Subprocess execution vulnerability",
    )

    pred2 = NormalizedFinding(
        finding_id="PRED-B",
        category="SECURITY",
        affected_file="app/api.py",
        line_start=16,
        line_end=16,
        title="Redundant warning on subprocess",
        explanation="Second alert on same line",
    )

    results, unmatched_gt, unmatched_pred = matcher.match([pred1, pred2], [gt])

    assert len(results) == 2
    tp_results = [r for r in results if r.matched and not r.is_duplicate]
    duplicate_results = [r for r in results if r.is_duplicate]

    assert len(tp_results) == 1
    assert len(duplicate_results) == 1
    assert duplicate_results[0].matched is False
    assert len(unmatched_gt) == 0


# ==============================================================================
# 4. Metrics Calculator Tests
# ==============================================================================


def test_metrics_calculator_standard_confusion_matrix() -> None:
    """Verify precision, recall, F1, FPR, and FNR calculations."""
    cm = ConfusionMatrix(
        true_positives=8,
        false_positives=2,
        false_negatives=2,
        true_negatives=0,
    )
    metrics = MetricsCalculator.calculate_from_confusion_matrix(cm)

    # Precision = 8 / (8 + 2) = 0.80
    assert metrics.precision == 0.8
    # Recall = 8 / (8 + 2) = 0.80
    assert metrics.recall == 0.8
    # F1 = 2 * (0.8 * 0.8) / (0.8 + 0.8) = 0.80
    assert metrics.f1_score == 0.8
    # FPR = 2 / 10 = 0.20
    assert metrics.false_positive_rate == 0.2
    # FNR = 2 / 10 = 0.20
    assert metrics.false_negative_rate == 0.2


def test_metrics_calculator_zero_division_safety() -> None:
    """Verify zero division returns 0.0 without throwing exceptions."""
    metrics = MetricsCalculator.calculate_metrics(
        true_positives=0,
        false_positives=0,
        false_negatives=0,
    )
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1_score == 0.0
    assert metrics.false_positive_rate == 0.0
    assert metrics.false_negative_rate == 0.0


def test_wilson_score_interval_bounds() -> None:
    """Verify Wilson score confidence interval produces valid probabilistic bounds."""
    # 80 successes out of 100 trials
    lower, upper = MetricsCalculator.wilson_score_interval(80, 100)
    assert 0.70 <= lower < 0.80
    assert 0.80 < upper <= 0.88

    # Edge cases
    assert MetricsCalculator.wilson_score_interval(0, 0) == (0.0, 0.0)
    zero_l, zero_u = MetricsCalculator.wilson_score_interval(0, 10)
    assert zero_l == 0.0 and zero_u > 0.0


def test_verification_metrics_calculator() -> None:
    """Verify calculation of critic rejection and evidence grounding rates."""
    vm = MetricsCalculator.calculate_verification_metrics(
        total_candidates=10,
        verified_count=7,
        rejected_count=3,
        evidence_grounded_count=6,
    )
    assert vm.verified_rate == 0.70
    assert vm.rejected_rate == 0.30
    assert vm.critic_rejection_rate == 0.30
    assert vm.evidence_grounded_rate == round(6 / 7, 4)


# ==============================================================================
# 5. Baseline Execution & Telemetry Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_static_analysis_baseline() -> None:
    """Test StaticAnalysisBaseline detects deterministic vulnerability patterns."""
    baseline = StaticAnalysisBaseline()

    # Load synthetic SQL injection case
    case_path = DATASETS_DIR / "synthetic/security/synth_sec_001.json"
    case = EvaluationCase.model_validate(
        json.loads(case_path.read_text(encoding="utf-8"))
    )

    findings, usage = await baseline.evaluate_case(case)

    assert len(findings) >= 1
    assert any("SQL Injection" in f.title for f in findings)
    assert usage.api_calls == 0
    assert usage.total_tokens == 0
    assert usage.estimated_cost_usd == 0.0
    assert usage.latency_seconds >= 0.0


@pytest.mark.asyncio
async def test_agentic_baseline_and_no_critic_ablation() -> None:
    """Verify Full Agentic baseline and No-Critic ablation behavior."""
    full_agentic = AgenticReviewerBaseline()
    no_critic = AgenticNoCriticBaseline()

    case_path = DATASETS_DIR / "synthetic/security/synth_sec_002.json"
    case = EvaluationCase.model_validate(
        json.loads(case_path.read_text(encoding="utf-8"))
    )

    # Full Agentic Reviewer
    findings_full, usage_full = await full_agentic.evaluate_case(case)
    assert len(findings_full) >= 1
    assert all(f.is_verified for f in findings_full)
    assert usage_full.api_calls > 0
    assert usage_full.total_tokens > 0

    # No-Critic Ablation
    findings_raw, usage_raw = await no_critic.evaluate_case(case)
    assert len(findings_raw) >= len(findings_full)
    assert usage_raw.api_calls == 5


# ==============================================================================
# 6. Benchmark Runner & Serialization Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_benchmark_runner_execution_and_serialization(tmp_path: Path) -> None:
    """Test end-to-end benchmark execution and JSON/CSV artifact serialization."""
    runner = BenchmarkRunner(
        dataset_dir=DATASETS_DIR,
        results_dir=tmp_path,
        git_commit_sha="0272942fd8b9267d8e798efffca9b831cd04cda1",
    )

    # Load a subset of 2 cases
    cases = runner.load_cases_from_directory(category_subdir="security")[:2]
    assert len(cases) == 2

    baseline = StaticAnalysisBaseline()
    run_result = await runner.run_benchmark(
        baseline=baseline,
        cases=cases,
        dataset_version="1.0.0",
        metadata={"environment": "pytest_isolated"},
    )

    assert run_result.total_cases == 2
    assert run_result.baseline_name == "static_analysis_only"
    assert run_result.git_commit_sha == "0272942fd8b9267d8e798efffca9b831cd04cda1"
    assert len(run_result.case_results) == 2

    # Verify JSON and CSV files were written to disk
    json_path = tmp_path / f"{run_result.run_id}_{baseline.name}.json"
    csv_path = tmp_path / f"{run_result.run_id}_{baseline.name}_summary.csv"

    assert json_path.exists(), "JSON result file must exist"
    assert csv_path.exists(), "CSV result file must exist"

    # Verify JSON deserializes cleanly
    saved_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_json["run_id"] == run_result.run_id
    assert "overall_metrics" in saved_json

    # Verify CSV has header and data line
    csv_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 2
    assert "true_positives" in csv_lines[0]
