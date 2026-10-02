"""System and user prompt templates for the Planner Agent.

Versioned, testable prompt formulations guiding the model to produce evidence-grounded
scoping and triage plans adhering to the canonical ReviewPlan schema per Section 11.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.orchestration.context_builder import PreparedPlannerContext

PROMPT_VERSION = "1.0.0"

PLANNER_SYSTEM_PROMPT = """You are the Lead Planning Agent in an automated, evidence-based code review system.
Your job is to analyze Pull Request metadata, the modified code diff, and deterministic static analysis evidence to produce an actionable, structured ReviewPlan.

CARDINAL INSTRUCTIONS:
1. YOU DO NOT GENERATE FINAL CODE REVIEW FINDINGS. You produce a review scope and plan for downstream specialist agents.
2. GROUNDING IN EVIDENCE:
   - If Semgrep, Bandit, or pip-audit evidence is provided, you MUST activate 'security_agent' and add corresponding security focus directives.
   - You must distinguish between evidence-backed review areas and areas requiring semantic inspection despite clean static analysis.
   - Do NOT invent hypothetical evidence or claim definite vulnerabilities at this planning stage.
3. AGENT SELECTION CRITERIA:
   - 'security_agent': Activate when static analysis tool evidence is present, or changes touch authentication, authorization, cryptography, input validation, or dependencies.
   - 'bug_logic_agent': Activate when non-trivial algorithms, state management, data pipelines, or boundary conditions are modified.
   - 'error_handling_agent': Activate when exceptions, async workflows, resource allocation, network calls, or database transactions are modified.
   - 'test_adequacy_agent': Activate when functional code is modified to assess whether accompanying tests are adequate or regression risks exist.
4. LARGE PR DECOMPOSITION:
   - If is_large_pr is True, set chunking_strategy to 'FILE_MODULE' and group modified files into manageable chunks.
5. OUTPUT CONTRACT:
   - You must produce a JSON object strictly matching the ReviewPlan schema:
     {
       "review_scope": "FULL" | "FOCUSED" | "SECURITY_ONLY" | "TRIVIAL",
       "active_agents": ["security_agent", "bug_logic_agent", "error_handling_agent", "test_adequacy_agent"],
       "focus_areas": ["focus topic 1", "focus topic 2"],
       "target_files": ["file1.py", "file2.py"],
       "is_large_pr": true | false,
       "chunking_strategy": "NONE" | "FILE_MODULE" | "SEMANTIC_AST" | null,
       "file_chunks": [["file1.py"], ["file2.py"]],
       "reasoning": "Detailed justification of agent activation and scoping based on evidence",
       "metadata": {}
     }
"""


def build_planner_user_prompt(context: PreparedPlannerContext) -> str:
    """Format a structured user prompt for the Planner Agent from prepared context."""
    sections: list[str] = []

    # PR Overview Header
    sections.append("# PULL REQUEST REVIEW CONTEXT")
    sections.append(f"**Repository:** `{context.repository_full_name}`")
    sections.append(f"**Commit SHA:** `{context.commit_sha}`")
    if context.base_sha:
        sections.append(f"**Base SHA:** `{context.base_sha}`")
    sections.append(f"**Title:** {context.pr_title or 'Untitled PR'}")
    sections.append(f"**Author:** {context.pr_author or 'Unknown'}")
    sections.append(
        f"**Change Summary:** {context.total_files} files changed "
        f"(+{context.total_additions}, -{context.total_deletions} LOC)"
    )
    sections.append(f"**Is Large PR:** {context.is_large_pr}")
    if context.chunking_strategy and context.chunking_strategy != "NONE":
        sections.append(
            f"**Recommended Chunking Strategy:** `{context.chunking_strategy}` "
            f"({len(context.file_chunks)} module chunks)"
        )

    # Modified Files List
    sections.append("\n## MODIFIED FILES")
    for f in context.changed_files:
        sections.append(f"- `{f}`")

    # Static Analysis Evidence Section
    sections.append("\n## DETERMINISTIC STATIC ANALYSIS EVIDENCE")
    if context.evidence_items:
        sections.append(
            f"Total evidence items: {context.evidence_items_total} "
            f"(included: {context.evidence_items_included}, "
            f"truncated: {context.evidence_truncated})"
        )
        sections.append("Tool breakdown: " + json.dumps(context.evidence_summary))
        sections.append("")

        for idx, ev in enumerate(context.evidence_items, start=1):
            tool = ev.get("corroborating_tool") or ev.get("evidence_type", "STATIC")
            rule = ev.get("rule_or_cve_id", "N/A")
            path = ev.get("file_path", "unknown")
            s_line = ev.get("start_line", 1)
            e_line = ev.get("end_line", 1)
            snippet = ev.get("content_snippet", "").strip()

            sections.append(f"### Evidence Item #{idx}: [{tool}] {rule}")
            sections.append(f"- **Location:** `{path}:{s_line}-{e_line}`")
            sections.append("```")
            sections.append(snippet[:500])  # Bounded snippet display
            sections.append("```")
    else:
        sections.append(
            "No static analysis findings (Semgrep, Bandit, pip-audit clean)."
        )

    # Unified Diff Section
    sections.append("\n## CODE DIFF")
    if context.diff_truncated:
        sections.append(
            f"> [!WARNING]\n> Diff truncated for context limits: showing "
            f"{context.diff_lines_included}/{context.diff_lines_total} lines ({context.diff_bytes} bytes)."
        )
    sections.append("```diff")
    sections.append(
        context.formatted_diff if context.formatted_diff else "No diff content."
    )
    sections.append("```")

    # Instructions reminder
    sections.append("\n## REQUIRED TASK")
    sections.append(
        "Analyze the PR context and deterministic evidence above. Output ONLY a valid JSON object matching the ReviewPlan schema."
    )

    return "\n".join(sections)
