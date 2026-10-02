"""Deterministic mapper from ReviewFinding to GitHub review comments.

Converts validated review findings into clean, structured Markdown comments
suitable for GitHub PR review discussions, ensuring:
- Clear separation between Issue, Evidence, and Recommendation
- Distinct severity presentation
- Proper GitHub suggestion block formatting
- Zero leakage of chain-of-thought, critic notes, prompts, or system metadata
"""

from app.schemas.enums import Severity
from app.schemas.finding import ReviewFinding
from app.schemas.publication import GitHubCommentPayload

_SEVERITY_BADGES = {
    Severity.CRITICAL: "🚨 **CRITICAL**",
    Severity.HIGH: "⚠️ **HIGH**",
    Severity.MEDIUM: "⚡ **MEDIUM**",
    Severity.LOW: "ℹ️ **LOW**",
    Severity.INFO: "💡 **INFO**",
}


def _format_suggestion_block(patch: str) -> str:
    """Format a code patch into a GitHub markdown suggestion block."""
    stripped = patch.strip()
    if stripped.startswith("```suggestion") and stripped.endswith("```"):
        return stripped
    if stripped.startswith("```") and stripped.endswith("```"):
        # Strip generic backticks
        lines = stripped.splitlines()
        if len(lines) >= 2:
            inner = "\n".join(lines[1:-1])
            return f"```suggestion\n{inner}\n```"
    return f"```suggestion\n{stripped}\n```"


def format_finding_comment(finding: ReviewFinding) -> str:
    """Format a ReviewFinding into a structured, production-quality GitHub review comment.

    Enforces strict architectural boundaries:
    - Never includes critic_notes, raw_confidence, agent_name, or internal traces.
    - Accurately renders issue description, evidence citations, and recommendations.
    - Attaches formatted code suggestions if provided.

    Args:
        finding: The verified ReviewFinding to render.

    Returns:
        str: Concise, formatted GitHub review comment body in Markdown.
    """
    badge = _SEVERITY_BADGES.get(finding.severity, f"**{finding.severity}**")
    lines: list[str] = [
        f"### {badge} — {finding.title.strip()}",
        "",
        f"**Category:** `{finding.issue_type}`",
        "",
        "#### Issue",
        finding.explanation.strip(),
        "",
        "#### Evidence",
    ]

    if finding.evidence:
        for item in finding.evidence:
            ev_type = str(item.evidence_type).replace("_", " ").title()
            tool_part = (
                f" ({item.corroborating_tool})" if item.corroborating_tool else ""
            )
            rule_part = f" [{item.rule_or_cve_id}]" if item.rule_or_cve_id else ""
            line_str = (
                f":{item.start_line}"
                if item.start_line == item.end_line
                else f":{item.start_line}-{item.end_line}"
            )
            loc = f"`{item.file_path}{line_str}`"
            snippet_preview = (
                item.snippet.strip().splitlines()[0]
                if item.snippet
                else "Verified repository evidence"
            )
            lines.append(
                f"- **{ev_type}{tool_part}{rule_part}** ({loc}): `{snippet_preview}`"
            )
    else:
        loc = f"`{finding.affected_file}:{finding.line_number}`"
        lines.append(f"- Location verified at {loc}")

    lines.extend(
        [
            "",
            "#### Recommendation",
            finding.recommendation.strip(),
        ]
    )

    if finding.suggested_patch and finding.suggested_patch.strip():
        lines.extend(
            [
                "",
                "#### Suggested Fix",
                _format_suggestion_block(finding.suggested_patch),
            ]
        )

    return "\n".join(lines)


def map_finding_to_comment_payload(finding: ReviewFinding) -> GitHubCommentPayload:
    """Map a ReviewFinding directly to a GitHubCommentPayload for API publication.

    Args:
        finding: Verified review finding.

    Returns:
        GitHubCommentPayload: Schema validated comment payload ready for GitHub API.
    """
    body = format_finding_comment(finding)
    return GitHubCommentPayload(
        path=finding.affected_file,
        line=finding.line_number,
        side=finding.side,
        body=body,
    )
