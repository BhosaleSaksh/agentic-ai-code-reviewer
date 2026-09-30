"""Unit tests for static analysis evidence normalization layer."""

from __future__ import annotations

import pytest
from app.schemas.enums import EvidenceType
from app.schemas.static_analysis import (
    BanditFinding,
    BanditResult,
    PipAuditFinding,
    PipAuditResult,
    SemgrepFinding,
    SemgrepResult,
    StaticAnalysisExecutionStatus,
    ToolAnalysisSummary,
)
from app.static_analysis.evidence_normalizer import (
    normalize_bandit_result,
    normalize_pip_audit_result,
    normalize_semgrep_result,
    normalize_tool_analysis_summary,
)
from app.static_analysis.path_utils import PathTraversalSecurityError


@pytest.fixture
def sample_semgrep_result() -> SemgrepResult:
    finding = SemgrepFinding(
        rule_id="python-dangerous-eval",
        message="Found dangerous use of dynamic eval() function.",
        severity="ERROR",
        file_path="app/eval_handler.py",
        start_line=12,
        end_line=14,
        start_col=5,
        end_col=20,
        metadata={"cwe": "CWE-95", "owasp": "A03:2021-Injection"},
    )
    return SemgrepResult(
        analyzer="semgrep",
        analyzer_version="1.78.0",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=0,
        duration_seconds=1.5,
        workspace_commit_sha="a" * 40,
        findings=[finding],
    )


@pytest.fixture
def sample_bandit_result() -> BanditResult:
    finding = BanditFinding(
        test_id="B307",
        test_name="blacklist",
        issue_text="Use of possibly insecure function - consider using safer ast.literal_eval.",
        severity="HIGH",
        confidence="HIGH",
        file_path="app/eval_handler.py",
        line_number=12,
        line_range=[12, 13, 14],
        code="result = eval(user_input)",
        more_info="https://bandit.readthedocs.io/en/latest/blacklists/blacklist_calls.html#b307-eval",
    )
    return BanditResult(
        analyzer="bandit",
        analyzer_version="1.9.4",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=1,
        duration_seconds=0.8,
        workspace_commit_sha="a" * 40,
        findings=[finding],
    )


@pytest.fixture
def sample_pip_audit_result() -> PipAuditResult:
    finding = PipAuditFinding(
        package_name="flask",
        package_version="0.12",
        vuln_id="PYSEC-2019-1010083",
        description="Unexpected memory use vulnerability in Flask.",
        fix_versions=["0.12.3"],
        aliases=["CVE-2019-1010083"],
        dependency_file="requirements.txt",
        line_number=5,
    )
    return PipAuditResult(
        analyzer="pip-audit",
        analyzer_version="2.7.3",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=1,
        duration_seconds=2.0,
        workspace_commit_sha="a" * 40,
        dependency_files_scanned=["requirements.txt"],
        findings=[finding],
    )


@pytest.mark.unit
def test_normalize_semgrep_result(sample_semgrep_result: SemgrepResult) -> None:
    evidence = normalize_semgrep_result(sample_semgrep_result)

    assert len(evidence) == 1
    item = evidence[0]

    assert item.evidence_type == EvidenceType.STATIC_ANALYSIS
    assert item.file_path == "app/eval_handler.py"
    assert item.start_line == 12
    assert item.end_line == 14
    assert "eval()" in item.snippet
    assert item.rule_or_cve_id == "python-dangerous-eval"
    assert item.corroborating_tool == "semgrep"

    # Provenance metadata
    assert item.metadata is not None
    assert item.metadata["analyzer"] == "semgrep"
    assert item.metadata["analyzer_version"] == "1.78.0"
    assert item.metadata["commit_sha"] == "a" * 40
    assert item.metadata["severity"] == "ERROR"
    assert item.metadata["rule_metadata"]["cwe"] == "CWE-95"


@pytest.mark.unit
def test_normalize_bandit_result(sample_bandit_result: BanditResult) -> None:
    evidence = normalize_bandit_result(sample_bandit_result)

    assert len(evidence) == 1
    item = evidence[0]

    assert item.evidence_type == EvidenceType.STATIC_ANALYSIS
    assert item.file_path == "app/eval_handler.py"
    assert item.start_line == 12
    assert item.end_line == 14
    assert item.snippet == "result = eval(user_input)"
    assert item.rule_or_cve_id == "bandit.B307"
    assert item.corroborating_tool == "bandit"

    assert item.metadata is not None
    assert item.metadata["test_id"] == "B307"
    assert item.metadata["severity"] == "HIGH"
    assert item.metadata["confidence"] == "HIGH"
    assert item.metadata["commit_sha"] == "a" * 40


@pytest.mark.unit
def test_normalize_pip_audit_result(sample_pip_audit_result: PipAuditResult) -> None:
    evidence = normalize_pip_audit_result(sample_pip_audit_result)

    assert len(evidence) == 1
    item = evidence[0]

    assert item.evidence_type == EvidenceType.DEPENDENCY
    assert item.file_path == "requirements.txt"
    assert item.start_line == 5
    assert item.end_line == 5
    assert "flask==0.12" in item.snippet
    assert "PYSEC-2019-1010083" in item.snippet
    assert item.rule_or_cve_id == "CVE-2019-1010083"  # Preferred from aliases
    assert item.corroborating_tool == "pip-audit"

    assert item.metadata is not None
    assert item.metadata["package_name"] == "flask"
    assert item.metadata["vuln_id"] == "PYSEC-2019-1010083"
    assert item.metadata["fix_versions"] == ["0.12.3"]
    assert item.metadata["commit_sha"] == "a" * 40


@pytest.mark.unit
def test_normalize_tool_analysis_summary(
    sample_semgrep_result: SemgrepResult,
    sample_bandit_result: BanditResult,
    sample_pip_audit_result: PipAuditResult,
) -> None:
    summary = ToolAnalysisSummary(
        semgrep=sample_semgrep_result,
        bandit=sample_bandit_result,
        pip_audit=sample_pip_audit_result,
        workspace_commit_sha="a" * 40,
        duration_seconds=4.3,
    )

    all_evidence = normalize_tool_analysis_summary(summary)

    assert len(all_evidence) == 3
    tools = [e.corroborating_tool for e in all_evidence]
    assert tools == ["semgrep", "bandit", "pip-audit"]

    # Verify uniform commit SHA across all items
    for item in all_evidence:
        assert item.metadata is not None
        assert item.metadata["commit_sha"] == "a" * 40


@pytest.mark.unit
def test_normalize_tool_analysis_summary_max_items_limit(
    sample_semgrep_result: SemgrepResult,
    sample_bandit_result: BanditResult,
    sample_pip_audit_result: PipAuditResult,
) -> None:
    summary = ToolAnalysisSummary(
        semgrep=sample_semgrep_result,
        bandit=sample_bandit_result,
        pip_audit=sample_pip_audit_result,
        workspace_commit_sha="a" * 40,
        duration_seconds=4.3,
    )

    # Limit to 2 items
    limited = normalize_tool_analysis_summary(summary, max_items=2)
    assert len(limited) == 2


@pytest.mark.unit
def test_normalize_path_traversal_rejection() -> None:
    bad_finding = SemgrepFinding(
        rule_id="bad-rule",
        message="Bad finding with directory traversal",
        severity="ERROR",
        file_path="../../etc/passwd",
        start_line=1,
        end_line=1,
    )
    bad_result = SemgrepResult(
        analyzer="semgrep",
        analyzer_version="1.78.0",
        execution_status=StaticAnalysisExecutionStatus.SUCCESS_WITH_FINDINGS,
        exit_code=0,
        duration_seconds=1.0,
        workspace_commit_sha="a" * 40,
        findings=[bad_finding],
    )

    with pytest.raises(PathTraversalSecurityError):
        normalize_semgrep_result(bad_result)
