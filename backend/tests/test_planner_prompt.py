"""Unit tests for Planner Agent prompt generation and templates."""

from app.agents.planner_prompt import (
    PLANNER_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_planner_user_prompt,
)
from app.orchestration.context_builder import PreparedPlannerContext


def test_planner_system_prompt_structure() -> None:
    """Verify system prompt contains cardinal rules and ReviewPlan contract."""
    assert PROMPT_VERSION == "1.0.0"
    assert "DO NOT GENERATE FINAL CODE REVIEW FINDINGS" in PLANNER_SYSTEM_PROMPT
    assert "security_agent" in PLANNER_SYSTEM_PROMPT
    assert "bug_logic_agent" in PLANNER_SYSTEM_PROMPT
    assert "error_handling_agent" in PLANNER_SYSTEM_PROMPT
    assert "test_adequacy_agent" in PLANNER_SYSTEM_PROMPT
    assert "ReviewPlan" in PLANNER_SYSTEM_PROMPT


def test_build_planner_user_prompt_with_evidence() -> None:
    """Verify prompt formatting when static analysis evidence is present."""
    context = PreparedPlannerContext(
        pr_title="Fix SQL Injection in user search",
        pr_author="alice",
        commit_sha="a" * 40,
        base_sha="b" * 40,
        repository_full_name="owner/repo",
        changed_files=["app/search.py"],
        total_files=1,
        total_additions=15,
        total_deletions=5,
        is_large_pr=False,
        chunking_strategy="NONE",
        file_chunks=[["app/search.py"]],
        evidence_items=[
            {
                "corroborating_tool": "semgrep",
                "rule_or_cve_id": "python.sql.injection",
                "file_path": "app/search.py",
                "start_line": 25,
                "end_line": 28,
                "content_snippet": 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")',
            }
        ],
        evidence_summary={"semgrep": 1},
        evidence_items_total=1,
        evidence_items_included=1,
        evidence_truncated=False,
        formatted_diff="+++ b/app/search.py\n+cursor.execute(query)",
        diff_lines_total=1,
        diff_lines_included=1,
        diff_bytes=40,
        diff_truncated=False,
    )

    prompt = build_planner_user_prompt(context)

    assert "Fix SQL Injection in user search" in prompt
    assert "owner/repo" in prompt
    assert "a" * 40 in prompt
    assert "app/search.py" in prompt
    assert "[semgrep] python.sql.injection" in prompt
    assert "SELECT * FROM users" in prompt
    assert "+++ b/app/search.py" in prompt


def test_build_planner_user_prompt_clean_static_analysis() -> None:
    """Verify prompt formatting when no static findings exist."""
    context = PreparedPlannerContext(
        pr_title="Refactor logging utility",
        pr_author="bob",
        commit_sha="a" * 40,
        base_sha=None,
        repository_full_name="owner/repo",
        changed_files=["app/logger.py"],
        total_files=1,
        total_additions=10,
        total_deletions=2,
        is_large_pr=False,
        chunking_strategy="NONE",
        file_chunks=[["app/logger.py"]],
        evidence_items=[],
        evidence_summary={},
        evidence_items_total=0,
        evidence_items_included=0,
        evidence_truncated=False,
        formatted_diff="+++ b/app/logger.py\n+logger.info('init')",
        diff_lines_total=1,
        diff_lines_included=1,
        diff_bytes=30,
        diff_truncated=False,
    )

    prompt = build_planner_user_prompt(context)

    assert "No static analysis findings" in prompt


def test_build_planner_user_prompt_truncation_warning() -> None:
    """Verify prompt highlights diff truncation when context limits were reached."""
    context = PreparedPlannerContext(
        pr_title="Massive feature branch",
        pr_author="carol",
        commit_sha="a" * 40,
        base_sha=None,
        repository_full_name="owner/repo",
        changed_files=["app/feat.py"],
        total_files=1,
        total_additions=1000,
        total_deletions=500,
        is_large_pr=True,
        chunking_strategy="FILE_MODULE",
        file_chunks=[["app/feat.py"]],
        evidence_items=[],
        evidence_summary={},
        evidence_items_total=0,
        evidence_items_included=0,
        evidence_truncated=False,
        formatted_diff="+++ b/app/feat.py\n+code",
        diff_lines_total=1500,
        diff_lines_included=400,
        diff_bytes=50000,
        diff_truncated=True,
    )

    prompt = build_planner_user_prompt(context)

    assert "Diff truncated for context limits: showing 400/1500 lines" in prompt
