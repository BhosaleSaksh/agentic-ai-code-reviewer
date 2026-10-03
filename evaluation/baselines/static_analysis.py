"""Baseline 1: Deterministic static analysis only (Semgrep / Bandit / AST heuristics)."""

from __future__ import annotations

import re
import time
import uuid

from evaluation.baselines.base import BaseBaseline
from evaluation.models.case import EvaluationInput
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class StaticAnalysisBaseline(BaseBaseline):
    """Deterministic analyzer executing standard security and syntactic pattern matching."""

    def __init__(self, mode: str = "offline") -> None:
        super().__init__(
            name="static_analysis_only",
            description="Pure static analysis using deterministic security and syntax heuristics (Bandit/Semgrep rules)",
            mode=mode,
        )
        self.provider_name = "bandit_semgrep_engine"
        self.model_name = "ast_and_regex_rulesets"

    async def evaluate_case(
        self, case: EvaluationInput
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Inspect vulnerable source code for deterministic static analysis signatures."""
        start_time = time.perf_counter()
        findings: list[NormalizedFinding] = []

        code = case.vulnerable_code
        lines = code.splitlines()

        # Rule 1: SQL Injection (Bandit B608)
        sql_pattern = re.compile(
            r'(?:cursor\.execute\s*\(|query\s*=\s*)?f["\'].*(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE).*\{',
            re.IGNORECASE,
        )
        # Rule 2: Hardcoded Secret (Bandit B105 / Semgrep hardcoded-jwt-secret)
        secret_pattern = re.compile(
            r'(?:api_key|secret_key|password|jwt_secret)\s*=\s*["\'][A-Za-z0-9_\-]{8,}["\']',
            re.IGNORECASE,
        )
        # Rule 3: Unsafe Deserialization (Bandit B301)
        pickle_pattern = re.compile(r"pickle\.loads?\s*\(", re.IGNORECASE)
        # Rule 4: Weak Hash MD5/SHA1 (Bandit B303)
        hash_pattern = re.compile(r"hashlib\.(?:md5|sha1)\s*\(", re.IGNORECASE)
        # Rule 5: Command Injection / shell=True (Bandit B602)
        shell_pattern = re.compile(
            r"subprocess\.(?:run|Popen|call)\s*\(.*shell\s*=\s*True", re.IGNORECASE
        )
        # Rule 6: Swallowed Exception / Bare Except Pass
        swallow_pattern = re.compile(r"except(?:\s+Exception)?:\s*pass", re.IGNORECASE)

        for line_idx, line in enumerate(lines, start=1):
            # Check SQL Injection
            if sql_pattern.search(line):
                findings.append(
                    NormalizedFinding(
                        finding_id=f"static-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=line_idx,
                        line_end=line_idx,
                        title="SQL Injection Vulnerability",
                        explanation="Detected unescaped parameter interpolation in SQL query execution (bandit.B608).",
                        confidence_score=0.95,
                        is_verified=True,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "bandit",
                                "rule_or_cve_id": "bandit.B608",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check Hardcoded Secret
            if secret_pattern.search(line):
                findings.append(
                    NormalizedFinding(
                        finding_id=f"static-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=line_idx,
                        line_end=line_idx,
                        title="Hardcoded Credential Detected",
                        explanation="Hardcoded authentication credential or cryptographic secret detected in source (bandit.B105).",
                        confidence_score=0.90,
                        is_verified=True,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "bandit",
                                "rule_or_cve_id": "bandit.B105",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check Unsafe Deserialization
            if pickle_pattern.search(line):
                findings.append(
                    NormalizedFinding(
                        finding_id=f"static-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="CRITICAL",
                        affected_file=case.affected_file,
                        line_start=line_idx,
                        line_end=line_idx,
                        title="Unsafe Object Deserialization",
                        explanation="Arbitrary code execution risk from untrusted object deserialization via pickle (bandit.B301).",
                        confidence_score=0.98,
                        is_verified=True,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "bandit",
                                "rule_or_cve_id": "bandit.B301",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check Weak Hash
            if hash_pattern.search(line):
                findings.append(
                    NormalizedFinding(
                        finding_id=f"static-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=line_idx,
                        line_end=line_idx,
                        title="Insecure Cryptographic Hash Function",
                        explanation="MD5 or SHA1 hash function is vulnerable to collision attacks (bandit.B303).",
                        confidence_score=0.95,
                        is_verified=True,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "bandit",
                                "rule_or_cve_id": "bandit.B303",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check Shell Command Injection
            if shell_pattern.search(line):
                findings.append(
                    NormalizedFinding(
                        finding_id=f"static-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=line_idx,
                        line_end=line_idx,
                        title="Subprocess Shell Execution Vulnerability",
                        explanation="Spawning subprocess with shell=True allows command injection (bandit.B602).",
                        confidence_score=0.92,
                        is_verified=True,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "bandit",
                                "rule_or_cve_id": "bandit.B602",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check Swallowed Exception
            if swallow_pattern.search(line):
                findings.append(
                    NormalizedFinding(
                        finding_id=f"static-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="LOW",
                        affected_file=case.affected_file,
                        line_start=line_idx,
                        line_end=line_idx,
                        title="Silent Exception Suppression",
                        explanation="Bare except block silently suppresses errors with pass (flake8-bugbear B110).",
                        confidence_score=0.85,
                        is_verified=True,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "flake8-bugbear",
                                "rule_or_cve_id": "flake8.B110",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

        elapsed = time.perf_counter() - start_time
        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        )

        return findings, usage
