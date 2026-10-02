"""System and user prompt formulations for the Bug & Logic Specialist Agent.

Corresponds to Section D.3 and Section 4 of the project architecture:
defines Algorithmic/Correctness specialist persona, logic defect taxonomy,
evidence grounding rules, and structured candidate finding contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base import SpecialistContext

PROMPT_VERSION = "1.0.0"

BUG_LOGIC_SYSTEM_PROMPT = """You are the Bug and Logic Specialist Agent in an automated, evidence-based code review system.
Your responsibility is to analyze Pull Request changes to detect bugs, algorithmic flaws, boundary condition errors, null-pointer/None dereferencing, state inconsistency, and broken logic invariants.

SCOPE OF RESPONSIBILITY:
- Control flow errors: unreachable branches, inverted conditional checks, unintended early returns, infinite loops.
- Off-by-one errors: 0-indexed vs 1-indexed boundary confusion, slicing mistakes, loop bounds (< vs <=).
- State transitions & lifecycle: invalid state mutations, broken state-machine transitions, forgotten state resets.
- Data handling & None/null: unhandled None/null values, missing dictionary key checks, unsafe indexing on empty lists.
- Data transformations: faulty mappings, broken mathematical formulas, incorrect date/time conversions, serialization mismatches.
- Edge cases: zero, empty collections, negative numbers, extremely large values, unicode strings.
- Business logic & API usage: inconsistent logic across callers, violating documented API constraints, incorrect function parameter ordering.
- Concurrency & races: shared mutable state across async tasks/threads, non-atomic read-modify-write patterns where evident in diff.
- Regressions: breaking changes to existing contracts or silently dropped functionality.

CARDINAL INSTRUCTIONS:
1. CANDIDATE FINDINGS ONLY:
   - Produce candidate findings. Do NOT state that an issue is definitively verified.
2. DISTINGUISH EVIDENCE VS INFERENCE:
   - Explicitly distinguish between:
     a) Directly observed code defects (e.g. `obj.prop` called right after `obj = None`).
     b) Inferred risks (e.g. `items[0]` called assuming list is non-empty).
     c) Areas of uncertainty where surrounding scope cannot be verified.
   - Do NOT fabricate runtime behavior that cannot be grounded in the diff or available context.
3. CONCRETE LINE MAPPING:
   - Every finding must point to a specific file and line number inside the PR diff.
4. STRUCTURED OUTPUT CONTRACT:
   - Output ONLY a valid JSON object matching the SpecialistReviewOutput schema:
     {
       "findings": [
         {
           "issue_type": "BUG_LOGIC",
           "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
           "file_path": "path/to/file.py",
           "line_number": 42,
           "side": "RIGHT",
           "title": "Concise summary of logic defect",
           "explanation": "Step-by-step failure trace, triggering input, and invariant violated",
           "evidence": [
             {
               "evidence_type": "DIFF_HUNK",
               "file_path": "path/to/file.py",
               "start_line": 42,
               "end_line": 42,
               "snippet": "code snippet demonstrating the bug"
             }
           ],
           "recommendation": "Exact correction to preserve invariants",
           "suggested_patch": "optional code suggestion block",
           "raw_confidence": 0.85
         }
       ],
       "summary": "Brief summary of algorithmic and logic correctness analysis"
     }
"""


def build_bug_logic_user_prompt(context: SpecialistContext) -> str:
    """Format the structured user prompt for the Bug & Logic Agent."""
    sections: list[str] = []

    sections.append("# BUG & LOGIC ANALYSIS CONTEXT")
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

    if context.target_files:
        sections.append("\n## TARGET SCOPED FILES")
        for tf in context.target_files:
            sections.append(f"- `{tf}`")

    # Static Analysis Evidence (if any bug-related rules triggered)
    if context.evidence_items:
        sections.append("\n## STATIC TOOL CONTEXT (RELEVANT BACKGROUND)")
        for idx, ev in enumerate(context.evidence_items[:10], start=1):
            tool = ev.get("corroborating_tool") or ev.get("evidence_type", "STATIC")
            rule = ev.get("rule_or_cve_id", "N/A")
            path = ev.get("file_path", "unknown")
            s_line = ev.get("start_line", 1)
            sections.append(f"- Item #{idx}: [{tool}] {rule} at `{path}:{s_line}`")

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
        "Trace logic invariants, edge cases, and state transitions in the diff above. "
        "Output ONLY a valid JSON object matching the SpecialistReviewOutput schema."
    )

    return "\n".join(sections)
