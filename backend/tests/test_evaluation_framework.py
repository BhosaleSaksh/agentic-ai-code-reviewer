"""Unit and integration tests for the Phase 7 evaluation and benchmarking framework.

Validates:
1. Dataset manifest integrity and schema compliance (all 23 cases)
2. Evaluation case schema and ground-truth isolation (leakage prevention via EvaluationInput)
3. Deterministic finding matching with line tolerance and duplicate handling
4. Adversarial matcher tests (same line different defect, one-to-one bipartite, duplicate penalization)
5. Metric calculations (Scenarios A through E, Precision, Recall, F1, FPR, FNR, Wilson score CIs)
6. Evidence grounding validation (EvidenceAuditor with adversarial tests)
7. Reviewer baselines and Critic ablation proof (agentic_no_critic FP > agentic_critic_full FP)
8. Fail-fast behavior for real mode when credentials are not configured
9. Benchmark execution runner and result serialization into evaluation/results/<run_id>/
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.baselines.ablation import (
    AgenticNoCriticBaseline,
    AgenticNoStaticEvidenceBaseline,
)
from evaluation.baselines.agentic import AgenticReviewerBaseline
from evaluation.baselines.single_llm import SingleLLMBaseline
from evaluation.baselines.static_analysis import StaticAnalysisBaseline
from evaluation.matching.evidence_auditor import EvidenceAuditor
from evaluation.matching.matcher import DeterministicFindingMatcher
from evaluation.metrics.calculator import MetricsCalculator
from evaluation.models.case import (
    CaseProvenance,
    DefectCategory,
    EvaluationCase,
    EvaluationInput,
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
    assert len(data["cases"]) == 5

    for case in data["cases"]:
        assert "case_id" in case
        assert "repository" in case
        assert "pr_number" in case
        assert "commit_sha" in case
        assert "ground_truth_authority" in case
        assert "annotation_uncertainty" in case
        assert case["annotation_uncertainty"] in {"LOW", "MEDIUM", "HIGH"}


def test_all_23_cases_conform_to_schema() -> None:
    """Verify all 18 synthetic cases and 5 real-world cases validate against EvaluationCase schema."""
    synth_files = list(DATASETS_DIR.glob("synthetic/*/*.json"))
    real_files = list(DATASETS_DIR.glob("real_world/*.json"))

    assert len(synth_files) == 18, (
        f"Expected 18 synthetic cases, found {len(synth_files)}"
    )
    assert len(real_files) == 5, f"Expected 5 real-world cases, found {len(real_files)}"
    assert len(synth_files) + len(real_files) == 23

    all_files = synth_files + real_files
    for file_path in all_files:
        content = json.loads(file_path.read_text(encoding="utf-8"))
        case = EvaluationCase.model_validate(content)
        assert case.case_id
        assert len(case.vulnerable_code) > 0
        assert len(case.ground_truth) >= 1

        for gt in case.ground_truth:
            assert gt.line_start <= gt.line_end
            assert gt.line_start >= 1
            assert len(gt.description) > 0
            assert gt.category in DefectCategory


# ==============================================================================
# 2. Leakage Prevention Isolation Tests
# ==============================================================================


def test_evaluation_case_leakage_isolation() -> None:
    """Verify to_evaluation_input strictly strips all ground-truth labels and descriptions."""
    case = EvaluationCase(
        case_id="SYNTH-SEC-TEST",
        category=DefectCategory.SECURITY,
        title="feat: implement search query",
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

    assert isinstance(model_input, EvaluationInput)
    assert not hasattr(model_input, "ground_truth")
    assert not hasattr(model_input, "expected_issue_type")
    assert not hasattr(model_input, "expected_severity")
    assert "Confidential ground-truth" not in str(model_input)
    assert model_input.affected_file == "app/users.py"
    assert model_input.vulnerable_code == case.vulnerable_code


# ==============================================================================
# 3. Deterministic Finding Matcher & Adversarial Tests (Part 10)
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


def test_matcher_adversarial_1_same_file_unrelated_defect() -> None:
    """Adversarial 1: Same file but unrelated defect (distance > tolerance) must not match."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)
    gt = GroundTruthDefect(
        defect_id="GT-01",
        category=DefectCategory.SECURITY,
        affected_file="app/auth.py",
        line_start=10,
        line_end=12,
        expected_issue_type="SQL_INJECTION",
        description="SQL injection",
        explanation="SQL injection",
    )
    pred = NormalizedFinding(
        finding_id="PRED-DISTANT",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/auth.py",
        line_start=90,
        line_end=92,
        title="Unrelated security flaw at bottom of file",
        explanation="Different issue",
    )
    results, unmatched_gt, unmatched_pred = matcher.match([pred], [gt])
    assert len(results) == 1
    assert results[0].matched is False
    assert len(unmatched_gt) == 1
    assert len(unmatched_pred) == 1


def test_matcher_adversarial_2_same_line_different_defect() -> None:
    """Adversarial 2: Same line but completely different defect category must NOT match."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)
    gt = GroundTruthDefect(
        defect_id="GT-SEC",
        category=DefectCategory.SECURITY,
        affected_file="app/auth.py",
        line_start=10,
        line_end=10,
        expected_issue_type="SQL_INJECTION",
        description="SQL injection",
        explanation="SQL injection",
    )
    # Prediction is at the EXACT SAME LINE (line 10), but category is TEST_ADEQUACY
    pred = NormalizedFinding(
        finding_id="PRED-TEST",
        category="TEST_ADEQUACY",
        severity="MEDIUM",
        affected_file="app/auth.py",
        line_start=10,
        line_end=10,
        title="Missing Unit Test",
        explanation="Missing unit test for this function",
    )
    results, unmatched_gt, unmatched_pred = matcher.match([pred], [gt])
    # Must NOT match as a True Positive!
    assert len(results) == 1
    assert results[0].matched is False
    assert len(unmatched_gt) == 1
    assert len(unmatched_pred) == 1


def test_matcher_adversarial_3_same_category_different_location() -> None:
    """Adversarial 3: Same category but different file must not match."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)
    gt = GroundTruthDefect(
        defect_id="GT-01",
        category=DefectCategory.SECURITY,
        affected_file="app/services/a.py",
        line_start=10,
        line_end=12,
        expected_issue_type="SQL_INJECTION",
        description="SQL injection",
        explanation="SQL injection",
    )
    pred = NormalizedFinding(
        finding_id="PRED-DIFF-FILE",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/services/b.py",
        line_start=10,
        line_end=12,
        title="SQL injection in file B",
        explanation="Different file",
    )
    results, unmatched_gt, unmatched_pred = matcher.match([pred], [gt])
    assert results[0].matched is False
    assert len(unmatched_gt) == 1


def test_matcher_adversarial_4_duplicate_prediction() -> None:
    """Adversarial 4 & 6: Two predictions targeting one ground-truth defect; only one is TP."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)
    gt = GroundTruthDefect(
        defect_id="GT-01",
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
        severity="HIGH",
        affected_file="app/api.py",
        line_start=15,
        line_end=15,
        title="Command injection issue",
        explanation="Subprocess execution vulnerability",
    )
    pred2 = NormalizedFinding(
        finding_id="PRED-B",
        category="SECURITY",
        severity="HIGH",
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
    assert len(unmatched_gt) == 0


def test_matcher_adversarial_5_one_prediction_two_ground_truths() -> None:
    """Adversarial 5: One prediction can match at most ONE ground truth defect (greedy 1-to-1)."""
    matcher = DeterministicFindingMatcher(line_tolerance=5)
    gt1 = GroundTruthDefect(
        defect_id="GT-01",
        category=DefectCategory.BUG_LOGIC,
        affected_file="app/logic.py",
        line_start=10,
        line_end=10,
        expected_issue_type="BOUNDARY_ERROR",
        description="Boundary 1",
        explanation="Defect 1",
    )
    gt2 = GroundTruthDefect(
        defect_id="GT-02",
        category=DefectCategory.BUG_LOGIC,
        affected_file="app/logic.py",
        line_start=12,
        line_end=12,
        expected_issue_type="BOUNDARY_ERROR",
        description="Boundary 2",
        explanation="Defect 2",
    )
    pred = NormalizedFinding(
        finding_id="PRED-SINGLE",
        category="BUG_LOGIC",
        affected_file="app/logic.py",
        line_start=10,
        line_end=12,
        title="Boundary error across range",
        explanation="Covers both lines",
    )
    results, unmatched_gt, unmatched_pred = matcher.match([pred], [gt1, gt2])
    # Single prediction can only claim ONE ground truth
    assert len(results) == 1
    assert results[0].matched is True
    # The remaining ground truth must be in unmatched_gt (False Negative)
    assert len(unmatched_gt) == 1


# ==============================================================================
# 4. Metric Validation Scenarios (Part 9)
# ==============================================================================


def test_metric_scenario_a() -> None:
    """Scenario A: TP=8, FP=2, FN=4."""
    matrix = ConfusionMatrix(
        true_positives=8, false_positives=2, false_negatives=4, true_negatives=0
    )
    assert matrix.true_positives == 8
    m = MetricsCalculator.calculate_metrics(
        true_positives=matrix.true_positives,
        false_positives=matrix.false_positives,
        false_negatives=matrix.false_negatives,
        true_negatives=matrix.true_negatives,
    )
    # Precision = 8 / (8 + 2) = 0.8000
    assert m.precision == 0.8
    # Recall = 8 / (8 + 4) = 8 / 12 = 0.6667
    assert m.recall == 0.6667
    # F1 = 2 * (0.8 * 0.6667) / (0.8 + 0.6667) = 0.7273
    assert m.f1_score == 0.7273
    # FNR = 4 / 12 = 0.3333
    assert m.false_negative_rate == 0.3333
    # DDR = Recall = 0.6667
    assert m.defect_detection_rate == 0.6667
    # When TN=0, False Discovery Rate is reported
    assert m.false_positive_rate == 0.2


def test_metric_scenario_b() -> None:
    """Scenario B: TP=0, FP=0, FN=5."""
    m = MetricsCalculator.calculate_metrics(
        true_positives=0, false_positives=0, false_negatives=5, true_negatives=0
    )
    assert m.precision == 0.0
    assert m.recall == 0.0
    assert m.f1_score == 0.0
    assert m.false_negative_rate == 1.0
    assert m.defect_detection_rate == 0.0
    assert m.false_positive_rate == 0.0


def test_metric_scenario_c() -> None:
    """Scenario C: TP=5, FP=5, FN=0."""
    m = MetricsCalculator.calculate_metrics(
        true_positives=5, false_positives=5, false_negatives=0, true_negatives=0
    )
    # Precision = 5 / 10 = 0.5000
    assert m.precision == 0.5
    # Recall = 5 / 5 = 1.0000
    assert m.recall == 1.0
    # F1 = 2 * (0.5 * 1.0) / (0.5 + 1.0) = 0.6667
    assert m.f1_score == 0.6667
    assert m.false_negative_rate == 0.0
    assert m.defect_detection_rate == 1.0
    assert m.false_positive_rate == 0.5


def test_metric_scenario_d_duplicate_penalization_metrics() -> None:
    """Scenario D: Duplicate predictions for one ground-truth defect."""
    # 1 defect. Reviewer emits 2 predictions (1 TP, 1 duplicate FP)
    m = MetricsCalculator.calculate_metrics(
        true_positives=1, false_positives=1, false_negatives=0
    )
    assert m.precision == 0.5
    assert m.recall == 1.0
    assert m.f1_score == 0.6667


def test_metric_scenario_e_multiple_defects_one_file() -> None:
    """Scenario E: Multiple ground-truth defects in one file (2 defects, 1 detected)."""
    m = MetricsCalculator.calculate_metrics(
        true_positives=1, false_positives=0, false_negatives=1
    )
    assert m.precision == 1.0
    assert m.recall == 0.5
    assert m.f1_score == 0.6667


# ==============================================================================
# 5. Evidence Grounding Validation (Part 11)
# ==============================================================================


def test_evidence_auditor_valid_evidence() -> None:
    """EvidenceAuditor accepts findings with authentic snippets present in code."""
    eval_input = EvaluationInput(
        case_id="TEST-01",
        category=DefectCategory.SECURITY,
        title="feat: test",
        description="test",
        affected_file="app/db.py",
        vulnerable_code="cursor.execute(f'SELECT * FROM users WHERE id={uid}')\n",
    )
    finding = NormalizedFinding(
        finding_id="F-01",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/db.py",
        line_start=1,
        line_end=1,
        title="SQL Injection",
        explanation="Direct formatting",
        evidence=[
            {
                "evidence_type": "STATIC_ANALYSIS",
                "corroborating_tool": "bandit",
                "content_snippet": "cursor.execute(f'SELECT * FROM users WHERE id={uid}')",
            }
        ],
    )
    assert EvidenceAuditor.is_finding_grounded(finding, eval_input) is True


def test_evidence_auditor_adversarial_rejections() -> None:
    """EvidenceAuditor rejects empty snippets, wrong files, invalid lines, and fictitious code."""
    eval_input = EvaluationInput(
        case_id="TEST-02",
        category=DefectCategory.SECURITY,
        title="feat: test",
        description="test",
        affected_file="app/db.py",
        vulnerable_code="line1 = 'hello'\nline2 = 'world'\n",
    )

    # 1. Empty snippet
    f1 = NormalizedFinding(
        finding_id="F-1",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/db.py",
        line_start=1,
        line_end=1,
        title="Empty Snippet",
        explanation="Empty snippet",
        evidence=[
            {
                "evidence_type": "STATIC_ANALYSIS",
                "corroborating_tool": "bandit",
                "content_snippet": "   ",
            }
        ],
    )
    assert EvidenceAuditor.is_finding_grounded(f1, eval_input) is False

    # 2. Nonexistent file
    f2 = NormalizedFinding(
        finding_id="F-2",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/db.py",
        line_start=1,
        line_end=1,
        title="Wrong File",
        explanation="Wrong file",
        evidence=[
            {
                "file_path": "other/nonexistent.py",
                "corroborating_tool": "bandit",
                "content_snippet": "line1",
            }
        ],
    )
    assert EvidenceAuditor.is_finding_grounded(f2, eval_input) is False

    # 3. Invalid line number beyond bounds
    f3 = NormalizedFinding(
        finding_id="F-3",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/db.py",
        line_start=1,
        line_end=1,
        title="Line Out of Bounds",
        explanation="Line 999",
        evidence=[
            {
                "line_number": 999,
                "corroborating_tool": "bandit",
                "content_snippet": "line1",
            }
        ],
    )
    assert EvidenceAuditor.is_finding_grounded(f3, eval_input) is False

    # 4. Fictitious snippet not in code
    f4 = NormalizedFinding(
        finding_id="F-4",
        category="SECURITY",
        severity="HIGH",
        affected_file="app/db.py",
        line_start=1,
        line_end=1,
        title="Hallucinated Snippet",
        explanation="Hallucination",
        evidence=[
            {
                "corroborating_tool": "bandit",
                "content_snippet": "import dangerous_exploit_module",
            }
        ],
    )
    assert EvidenceAuditor.is_finding_grounded(f4, eval_input) is False


# ==============================================================================
# 6. Critic Ablation Controlled Proof (Part 5)
# ==============================================================================


@pytest.mark.asyncio
async def test_critic_ablation_proves_false_positive_elimination() -> None:
    """Verify that agentic_no_critic emits speculative candidate findings (FP > 0)

    while agentic_critic_full verifies and rejects them (FP == 0), proving Critic value.
    """
    critic_full = AgenticReviewerBaseline(mode="offline")
    no_critic = AgenticNoCriticBaseline(mode="offline")

    case_path = DATASETS_DIR / "synthetic/security/synth_sec_001.json"
    case = EvaluationCase.model_validate(
        json.loads(case_path.read_text(encoding="utf-8"))
    )

    eval_input = case.to_evaluation_input()

    # 1. Run No-Critic Ablation
    findings_no_critic, _ = await no_critic.evaluate_case(eval_input)

    # 2. Run Full Critic Reviewer
    findings_critic_full, _ = await critic_full.evaluate_case(eval_input)

    # The No-Critic ablation must emit MORE findings than the full critic
    # because it includes the unverified speculative candidates!
    assert len(findings_no_critic) > len(findings_critic_full)

    matcher = DeterministicFindingMatcher()
    _, _, unverified_fps = matcher.match(findings_no_critic, case.ground_truth)
    _, _, verified_fps = matcher.match(findings_critic_full, case.ground_truth)

    # In no_critic, unverified candidate findings become False Positives!
    assert len(unverified_fps) > 0, "agentic_no_critic must produce FP > 0"
    # In critic_full, the Critic filters out the unverified findings!
    assert len(verified_fps) == 0, "agentic_critic_full must eliminate spurious FPs"


@pytest.mark.asyncio
async def test_agentic_no_static_evidence_baseline() -> None:
    """Verify that agentic_no_static_evidence strips static analysis findings."""
    baseline = AgenticNoStaticEvidenceBaseline(mode="offline")
    assert baseline.name == "agentic_no_static_evidence"

    case_path = DATASETS_DIR / "synthetic/security/synth_sec_001.json"
    case = EvaluationCase.model_validate(
        json.loads(case_path.read_text(encoding="utf-8"))
    )
    eval_input = case.to_evaluation_input()
    findings, usage = await baseline.evaluate_case(eval_input)
    assert len(findings) > 0
    # In this ablation, static tools (bandit, semgrep) must not be corroborating tools
    for f in findings:
        for ev in f.evidence:
            tool = ev.get("corroborating_tool", "").lower()
            assert tool not in ("bandit", "semgrep")


# ==============================================================================
# 7. Real Mode Fail-Fast Credentials Verification (Part 3 & Part 12)
# ==============================================================================


@pytest.mark.asyncio
async def test_real_mode_fails_fast_when_credentials_missing() -> None:
    """Verify that requesting mode='real' without provisioned API keys raises RuntimeError."""
    from app.core.config import Settings
    from app.services.llm.service import LLMService

    unconfigured_service = LLMService(
        settings=Settings(LLM_PROVIDER="openai", OPENAI_API_KEY="")
    )
    baseline = SingleLLMBaseline(llm_service=unconfigured_service, mode="real")
    eval_input = EvaluationInput(
        case_id="TEST-REAL",
        category=DefectCategory.SECURITY,
        title="test",
        description="test",
        affected_file="test.py",
        vulnerable_code="print('hello')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        await baseline.evaluate_case(eval_input)

    assert "Real LLM mode requested" in str(exc_info.value)
    assert "credentials are not configured" in str(exc_info.value)


# ==============================================================================
# 8. Benchmark Runner & Isolated Run Directory (Part 14)
# ==============================================================================


@pytest.mark.asyncio
async def test_benchmark_runner_isolated_run_directory(tmp_path: Path) -> None:
    """Test that every benchmark run creates a unique isolated results/<run_id>/ directory."""
    runner = BenchmarkRunner(
        dataset_dir=DATASETS_DIR,
        results_dir=tmp_path,
        git_commit_sha="af0f0427252487b6cd0b76bba14a0d611fd67024",
    )

    cases = runner.load_all_cases(include_real_world=True)[:2]
    assert len(cases) == 2

    baseline = StaticAnalysisBaseline(mode="offline")
    run_result = await runner.run_benchmark(
        baseline=baseline,
        cases=cases,
        dataset_version="1.0.0",
        metadata={"environment": "pytest_run_dir"},
    )

    # Check isolated run directory exists: evaluation/results/<run_id>/
    run_dir = tmp_path / run_result.run_id
    assert run_dir.exists(), f"Directory {run_dir} must exist"
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "cases.json").exists()
    assert (run_dir / "metrics.csv").exists()
    assert (run_dir / "config.json").exists()

    config_data = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert config_data["execution_mode"] == "offline_mock"
    assert config_data["baseline_name"] == "static_analysis_only"
