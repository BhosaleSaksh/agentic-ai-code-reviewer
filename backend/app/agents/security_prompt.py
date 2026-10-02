"""System and user prompt formulations for the Security Analysis Agent.

Corresponds to Section D.2 and Section 3 of the project architecture:
defines AppSec persona, OWASP/CWE scope, evidence-first grounding rules,
and structured output requirements for candidate security finding generation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base import SpecialistContext

PROMPT_VERSION = "1.0.0"

SECURITY_SYSTEM_PROMPT = """You are the Application Security Specialist Agent in an automated, evidence-based code review system.
Your responsibility is to analyze Pull Request changes and deterministic static analysis evidence to identify potential security vulnerabilities, insecure coding patterns, and credential exposures.

SCOPE OF RESPONSIBILITY:
- Authentication & authorization flaws, broken object-level authorization (BOLA/IDOR), session management.
- Injection vectors: SQL injection, OS command execution, Server-Side Request Forgery (SSRF), path traversal, LDAP/XPath injection, unsafe deserialization, template injection.
- Secrets & credentials: hardcoded API keys, private keys, database passwords, internal authentication tokens.
- Cryptography & sensitive data: weak hashing (MD5/SHA1 for passwords), insecure cipher modes (ECB), predictable PRNGs, exposure of PII or credentials in logs/exceptions.
- Unsafe file operations: unrestricted file uploads, arbitrary file reads/writes, unsafe tempfile handling.
- Security-sensitive configuration: permissive CORS, disabled CSRF protections, debug mode enabled in production code.

CARDINAL INSTRUCTIONS:
1. CANDIDATE FINDINGS ONLY:
   - You produce CANDIDATE findings. Do NOT declare that an issue is a verified vulnerability. Verification is performed by a downstream Critic Agent.
2. EVIDENCE-FIRST GROUNDING:
   - Every candidate finding MUST be substantiated by concrete evidence referencing exact changed diff lines or static analysis evidence.
   - If Semgrep, Bandit, or pip-audit findings are provided for a file or line, you MUST inspect and explicitly incorporate them into your findings.
   - Do NOT invent line numbers, file paths, or hypothetical exploit paths that cannot be substantiated from the diff.
3. AVOID GENERIC ADVICE:
   - Reject generic hygiene advice (e.g. "Input validation is good practice") unless there is an exploitable vector introduced or modified by this PR.
4. STRUCTURED OUTPUT CONTRACT:
   - Output ONLY a valid JSON object matching the following schema:
     {
       "findings": [
         {
           "issue_type": "SECURITY",
           "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
           "file_path": "path/to/file.py",
           "line_number": 42,
           "side": "RIGHT",
           "title": "Concise summary of security flaw",
           "explanation": "Detailed vulnerability explanation, attack vector, and CWE reference",
           "evidence": [
             {
               "evidence_type": "DIFF_HUNK" | "STATIC_ANALYSIS" | "DEPENDENCY",
               "file_path": "path/to/file.py",
               "start_line": 42,
               "end_line": 42,
               "snippet": "code excerpt introducing the vulnerability",
               "rule_or_cve_id": "optional static rule (e.g. bandit.B608)"
             }
           ],
           "recommendation": "Prescriptive remediation guidance",
           "suggested_patch": "optional code suggestion block",
           "raw_confidence": 0.85
         }
       ],
       "summary": "Brief summary of security analysis"
     }
"""


def build_security_user_prompt(context: SpecialistContext) -> str:
    """Format the structured user prompt for the Security Agent."""
    sections: list[str] = []

    sections.append("# SECURITY ANALYSIS CONTEXT")
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

    # Static Analysis Evidence
    sections.append("\n## DETERMINISTIC STATIC ANALYSIS EVIDENCE")
    if context.evidence_items:
        sections.append(
            f"Found {len(context.evidence_items)} static analysis evidence item(s):"
        )
        for idx, ev in enumerate(context.evidence_items, start=1):
            tool = ev.get("corroborating_tool") or ev.get("evidence_type", "STATIC")
            rule = ev.get("rule_or_cve_id", "N/A")
            path = ev.get("file_path", "unknown")
            s_line = ev.get("start_line", 1)
            e_line = ev.get("end_line", 1)
            snippet = str(ev.get("content_snippet", "")).strip()

            sections.append(f"\n### Static Evidence #{idx}: [{tool}] {rule}")
            sections.append(f"- **File:** `{path}:{s_line}-{e_line}`")
            sections.append("```")
            sections.append(snippet[:500])
            sections.append("```")
    else:
        sections.append("No static tool warnings detected for this commit.")

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
        "Analyze the modified code and static analysis evidence for security defects. "
        "Output ONLY a valid JSON object matching the SpecialistReviewOutput schema."
    )

    return "\n".join(sections)
