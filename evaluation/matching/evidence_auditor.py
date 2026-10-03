"""Evidence grounding validation engine for benchmark evaluation."""

from __future__ import annotations

from evaluation.matching.matcher import DeterministicFindingMatcher
from evaluation.models.case import EvaluationInput
from evaluation.models.finding import NormalizedFinding


class EvidenceAuditor:
    """Audits whether reviewer findings are genuinely evidence-grounded.

    Rejects findings where evidence is empty, fictitious, points to invalid lines/files,
    or contains code snippets not present in the code under review.
    """

    VALID_TOOLS = {
        "bandit",
        "semgrep",
        "pip_audit",
        "ast_analyzer",
        "dataflow_analyzer",
        "symbolic_verifier",
        "state_machine_checker",
        "arithmetic_verifier",
        "logic_verifier",
        "flake8-bugbear",
        "resource_analyzer",
        "security_policy_checker",
        "coverage_diff_checker",
        "mutation_testing_analyzer",
        "git_blame_diff_checker",
        "security_advisory",
        "exception_coverage_analyzer",
        "test_coverage_analyzer",
    }

    VALID_EVIDENCE_TYPES = {
        "STATIC_ANALYSIS",
        "CONTEXT_EXPANSION",
        "TOOL_CORROBORATION",
    }

    @classmethod
    def is_finding_grounded(
        cls, finding: NormalizedFinding, case: EvaluationInput
    ) -> bool:
        """Determine whether a finding is legitimately grounded by valid evidence.

        A finding is grounded only if at least one evidence item satisfies all criteria:
        1. Non-empty snippet (not just whitespace)
        2. Valid corroborating tool or evidence type
        3. File path matches case under review (if specified)
        4. Line coordinates are within valid file bounds (if specified)
        5. Content snippet actually exists within the code under review
        """
        if not finding.evidence or len(finding.evidence) == 0:
            return False

        code_lines = case.vulnerable_code.splitlines()
        code_full = case.vulnerable_code

        valid_grounded_items = 0

        for item in finding.evidence:
            if not isinstance(item, dict):
                continue

            snippet = item.get("content_snippet", "").strip()
            if not snippet:
                # Empty snippet is ungrounded
                continue

            # Verify tool or evidence type
            tool = item.get("corroborating_tool", "").lower()
            ev_type = item.get("evidence_type", "").upper()
            if tool not in cls.VALID_TOOLS and ev_type not in cls.VALID_EVIDENCE_TYPES:
                continue

            # Verify file path if provided
            evidence_file = item.get("file_path")
            if evidence_file and not DeterministicFindingMatcher.paths_match(
                evidence_file, case.affected_file
            ):
                # Points to nonexistent or mismatched file
                continue

            # Verify line number if provided
            line_no = item.get("line_number")
            if line_no is not None and (line_no < 1 or line_no > len(code_lines)):
                # Invalid line number out of range
                continue

            # Verify content snippet exists in code under review (normalized whitespace)
            clean_snippet = " ".join(snippet.split())
            clean_code = " ".join(code_full.split())
            if clean_snippet not in clean_code and snippet not in code_full:
                # Hallucinated snippet or unrelated diff hunk
                continue

            valid_grounded_items += 1

        return valid_grounded_items > 0
