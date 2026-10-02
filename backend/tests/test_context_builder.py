"""Unit tests for PlannerContextBuilder: diff bounding, evidence grounding, and large PR triage."""

import pytest
from app.orchestration.context_builder import PlannerContextBuilder
from app.orchestration.errors import EvidenceValidationError
from app.schemas.diff import DiffFile, DiffHunk, DiffLine, ParsedDiff
from app.schemas.enums import DiffLineType, EvidenceType, FileChangeType
from app.schemas.evidence import EvidenceModel


def _build_test_diff(num_lines: int, filename: str = "app/main.py") -> ParsedDiff:
    """Helper to generate synthetic ParsedDiff with a specified number of lines."""
    lines: list[DiffLine] = []
    for i in range(1, num_lines + 1):
        lines.append(
            DiffLine(
                line_type=DiffLineType.ADDED,
                new_line_number=i,
                content=f"x_{i} = {i}",
            )
        )

    hunk = DiffHunk(
        old_start=0,
        old_count=0,
        new_start=1,
        new_count=num_lines,
        header=f"@@ -0,0 +1,{num_lines} @@",
        lines=lines,
    )
    diff_file = DiffFile(
        old_path=None,
        new_path=filename,
        status=FileChangeType.ADDED,
        hunks=[hunk],
    )
    return ParsedDiff(files=[diff_file])


def test_context_builder_bounds_diff_lines() -> None:
    """Verify that diff lines exceeding max_diff_lines are truncated."""
    builder = PlannerContextBuilder(max_diff_lines=20, max_diff_bytes=100_000)
    parsed_diff = _build_test_diff(50)

    pr_ctx = {
        "repository_full_name": "owner/repo",
        "head_sha": "a" * 40,
        "parsed_diff": parsed_diff,
        "changed_files": ["app/main.py"],
    }

    ctx = builder.build(
        pr_context=pr_ctx,
        evidence_items=[],
        expected_commit_sha="a" * 40,
    )

    assert ctx.diff_truncated is True
    assert ctx.diff_lines_included == 20
    assert ctx.diff_lines_total == 50


def test_context_builder_excludes_sensitive_files() -> None:
    """Verify that sensitive files like .env or keys have their diff contents excluded."""
    builder = PlannerContextBuilder()
    diff1 = _build_test_diff(10, filename=".env")
    diff2 = _build_test_diff(10, filename="id_rsa")
    diff3 = _build_test_diff(10, filename="app/utils.py")

    combined_diff = ParsedDiff(files=[diff1.files[0], diff2.files[0], diff3.files[0]])
    pr_ctx = {
        "repository_full_name": "owner/repo",
        "head_sha": "a" * 40,
        "parsed_diff": combined_diff,
    }

    ctx = builder.build(
        pr_context=pr_ctx,
        evidence_items=[],
        expected_commit_sha="a" * 40,
    )

    assert "[EXCLUDED: SENSITIVE FILE]" in ctx.formatted_diff
    assert "+++ b/app/utils.py" in ctx.formatted_diff


def test_context_builder_deduplicates_and_bounds_evidence() -> None:
    """Verify evidence items are deduplicated and capped at max_evidence_items."""
    builder = PlannerContextBuilder(max_evidence_items=2)

    ev1 = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="app/auth.py",
        start_line=10,
        end_line=12,
        snippet="password = 'secret'",
        corroborating_tool="semgrep",
        rule_or_cve_id="rule-1",
    )
    # Duplicate of ev1
    ev1_dup = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="app/auth.py",
        start_line=10,
        end_line=12,
        snippet="password = 'secret'",
        corroborating_tool="semgrep",
        rule_or_cve_id="rule-1",
    )
    ev2 = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="app/db.py",
        start_line=20,
        end_line=22,
        snippet="cursor.execute(query)",
        corroborating_tool="bandit",
        rule_or_cve_id="B608",
    )
    ev3 = EvidenceModel(
        evidence_type=EvidenceType.DEPENDENCY,
        file_path="pyproject.toml",
        start_line=1,
        end_line=1,
        snippet="vulnerable-pkg==1.0",
        corroborating_tool="pip-audit",
        rule_or_cve_id="CVE-2024-1234",
    )

    ctx = builder.build(
        pr_context={"repository_full_name": "owner/repo", "head_sha": "a" * 40},
        evidence_items=[ev1, ev1_dup, ev2, ev3],
        expected_commit_sha="a" * 40,
    )

    assert ctx.evidence_truncated is True
    assert ctx.evidence_items_included == 2
    assert ctx.evidence_items_total == 4
    assert ctx.evidence_summary["semgrep"] == 1
    assert ctx.evidence_summary["bandit"] == 1


def test_context_builder_detects_commit_mismatch_in_pr() -> None:
    """Verify that mismatch between PR head_sha and expected_commit_sha raises EvidenceValidationError."""
    builder = PlannerContextBuilder()
    pr_ctx = {
        "repository_full_name": "owner/repo",
        "head_sha": "b" * 40,
    }

    with pytest.raises(
        EvidenceValidationError, match="Commit SHA mismatch in PR context"
    ):
        builder.build(
            pr_context=pr_ctx,
            evidence_items=[],
            expected_commit_sha="a" * 40,
        )


def test_context_builder_detects_commit_mismatch_in_evidence() -> None:
    """Verify that evidence generated for an old commit SHA raises EvidenceValidationError."""
    builder = PlannerContextBuilder()
    stale_evidence = EvidenceModel(
        evidence_type=EvidenceType.STATIC_ANALYSIS,
        file_path="app/main.py",
        start_line=1,
        end_line=2,
        snippet="code",
        metadata={"commit_sha": "c" * 40},
    )

    with pytest.raises(EvidenceValidationError, match="belongs to commit"):
        builder.build(
            pr_context={"repository_full_name": "owner/repo", "head_sha": "a" * 40},
            evidence_items=[stale_evidence],
            expected_commit_sha="a" * 40,
        )


def test_context_builder_large_pr_detection_and_chunking() -> None:
    """Verify large PR triage activates FILE_MODULE chunking when LOC > threshold."""
    builder = PlannerContextBuilder(large_pr_loc_threshold=400)
    # PR with 450 additions
    large_diff = _build_test_diff(450, filename="backend/app/auth/login.py")

    pr_ctx = {
        "repository_full_name": "owner/repo",
        "head_sha": "a" * 40,
        "parsed_diff": large_diff,
        "changed_files": [
            "backend/app/auth/login.py",
            "backend/app/auth/jwt.py",
            "backend/app/db/models.py",
        ],
    }

    ctx = builder.build(
        pr_context=pr_ctx,
        evidence_items=[],
        expected_commit_sha="a" * 40,
    )

    assert ctx.is_large_pr is True
    assert ctx.chunking_strategy == "FILE_MODULE"
    assert len(ctx.file_chunks) > 0


def test_context_builder_raw_diff_and_byte_bounding() -> None:
    """Verify raw diff fallback and byte limit bounding."""
    builder = PlannerContextBuilder(max_diff_lines=100, max_diff_bytes=50)
    raw_diff = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"

    pr_ctx = {
        "repository_full_name": "owner/repo",
        "head_sha": "a" * 40,
        "raw_diff": raw_diff,
        "changed_files": ["file.txt"],
    }

    ctx = builder.build(
        pr_context=pr_ctx,
        evidence_items=[],
        expected_commit_sha="a" * 40,
    )

    assert ctx.diff_truncated is True
    assert ctx.diff_lines_included < 10


def test_context_builder_unsupported_type() -> None:
    """Verify passing an invalid type raises TypeError."""
    builder = PlannerContextBuilder()
    with pytest.raises(TypeError, match="Unsupported pr_context type"):
        builder.build(
            pr_context="invalid_type",  # type: ignore[arg-type]
            evidence_items=[],
            expected_commit_sha="a" * 40,
        )


def test_context_builder_partition_empty_files() -> None:
    """Verify partition with empty changed_files returns empty list."""
    builder = PlannerContextBuilder()
    assert builder._partition_files_into_chunks([]) == []

    # With root files
    chunks = builder._partition_files_into_chunks(["README.md", "pyproject.toml"])
    assert len(chunks) == 1
    assert "README.md" in chunks[0]
