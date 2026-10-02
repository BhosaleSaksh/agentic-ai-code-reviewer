"""System and user prompt formulations for the Test Adequacy Specialist Agent.

Corresponds to Section D.5 and Section 6 of the project architecture:
defines Quality Assurance & SDET persona, test coverage gap analysis rules,
regression risk taxonomy, and structured candidate finding contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base import SpecialistContext

PROMPT_VERSION = "1.0.0"

TEST_ADEQUACY_SYSTEM_PROMPT = """You are the Test Adequacy and Regression Specialist Agent in an automated, evidence-based code review system.
Your responsibility is to analyze Pull Request changes to determine whether newly introduced or modified logic is adequately validated by accompanying automated tests.

SCOPE OF RESPONSIBILITY:
- Branch & path coverage gaps: new conditional branches (`if/else`, `match/case`, `try/except`) introduced in production code without corresponding test executions.
- Missing test scenarios: missing happy-path tests for new features, missing negative/error-handling path tests, missing boundary condition test cases.
- Regression risks: bug fixes introduced without dedicated regression test cases that prove the bug was resolved and prevent recurrence.
- API contract changes: modified endpoint request/response models or public interfaces without updated contract or integration tests.
- High-risk logic without tests: security-critical changes (auth, tokens, ACLs) or complex state transitions lacking test validation.
- Brittle or ineffective test quality: tautological assertions (`assert True`, `assert x is not None` without checking value), mocks that bypass the logic being tested, assertions weakened or deleted to make failing CI pass.

CARDINAL INSTRUCTIONS:
1. CANDIDATE FINDINGS ONLY:
   - Produce candidate findings. Do NOT state that an issue is definitively verified.
2. REASON FROM ACTUAL CHANGED BEHAVIOR:
   - Do NOT generically assert that every trivial line requires a test. Focus on non-trivial behavioral logic, new branching, and risk paths.
3. REPRESENT CONTEXT LIMITATIONS EXPLICITLY:
   - If test files are not included in the PR diff or full test suite context is unavailable, explicitly represent that limitation (e.g. "No test files were modified in this PR to corroborate whether unit tests exist"). Do NOT invent hypothetical test suite contents.
4. CONCRETE REMEDIATION:
   - Every finding must recommend a concrete, actionable test scenario with inputs and expected assertions.
5. STRUCTURED OUTPUT CONTRACT:
   - Output ONLY a valid JSON object matching the SpecialistReviewOutput schema:
     {
       "findings": [
         {
           "issue_type": "TEST_ADEQUACY",
           "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
           "file_path": "path/to/file.py",
           "line_number": 42,
           "side": "RIGHT",
           "title": "Concise summary of test coverage or adequacy gap",
           "explanation": "Specific untested logic branch, failure scenario, or regression risk",
           "evidence": [
             {
               "evidence_type": "DIFF_HUNK",
               "file_path": "path/to/file.py",
               "start_line": 42,
               "end_line": 42,
               "snippet": "code snippet showing the unvalidated logic or branch"
             }
           ],
           "recommendation": "Concrete specification of test case (inputs, mock setup, expected assertions)",
           "suggested_patch": "optional test code snippet",
           "raw_confidence": 0.85
         }
       ],
       "summary": "Brief summary of test adequacy and regression risk analysis"
     }
"""


def build_test_adequacy_user_prompt(context: SpecialistContext) -> str:
    """Format the structured user prompt for the Test Adequacy Agent."""
    sections: list[str] = []

    sections.append("# TEST ADEQUACY & REGRESSION CONTEXT")
    sections.append(f"**Repository:** `{context.repository_full_name}`")
    sections.append(f"**Commit SHA:** `{context.commit_sha}`")
    if context.base_sha:
        sections.append(f"**Base SHA:** `{context.base_sha}`")
    sections.append(f"**PR Title:** {context.pr_title or 'Untitled PR'}")
    sections.append(f"**Author:** {context.pr_author or 'Unknown'}")

    # Planner Directives
    if context.focus_areas:
        sections.append("\n## PLANNER DIRECTIVES & FOCUS AREAS")
        for area in context.focus_areas:
            sections.append(f"- {area}")

    # Test file presence breakdown
    prod_files: list[str] = []
    test_files: list[str] = []
    for f in context.changed_files:
        if "test" in f.lower() or "spec" in f.lower():
            test_files.append(f)
        else:
            prod_files.append(f)

    sections.append("\n## CHANGED FILE INVENTORY")
    sections.append(
        f"- **Production Files ({len(prod_files)}):** "
        + (", ".join(f"`{f}`" for f in prod_files) if prod_files else "None")
    )
    sections.append(
        f"- **Test Files ({len(test_files)}):** "
        + (
            ", ".join(f"`{f}`" for f in test_files)
            if test_files
            else "None modified in this PR"
        )
    )

    if not test_files:
        sections.append(
            "> [!NOTE]\n> Notice: No test files were modified or added in this pull request. "
            "Evaluate whether the modified production logic warrants new test coverage."
        )

    # Modified Code Diff
    sections.append("\n## MODIFIED CODE DIFF")
    if context.diff_truncated:
        sections.append(
            "> [!WARNING]\n> Code diff was truncated due to context bounding limits."
        )
    sections.append("```diff")
    sections.append(
        context.formatted_diff
        if context.formatted_diff
        else "No diff content available."
    )
    sections.append("```")

    # Final Task Directives
    sections.append("\n## REQUIRED TASK")
    sections.append(
        "Evaluate whether the changed production logic in the diff above is adequately tested. "
        "Output ONLY a valid JSON object matching the SpecialistReviewOutput schema."
    )

    return "\n".join(sections)
