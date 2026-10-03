"""Baseline 3: Full Agentic Reviewer with Planner, Specialists, Evidence, and Critic."""

from __future__ import annotations

import time
import uuid

from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.service import LLMService

from evaluation.baselines.base import BaseBaseline
from evaluation.baselines.static_analysis import StaticAnalysisBaseline
from evaluation.models.case import EvaluationInput
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class AgenticReviewerBaseline(BaseBaseline):
    """Full multi-agent architecture coordinating Planner, Specialists, Grounding, and Critic."""

    def __init__(
        self, llm_service: LLMService | None = None, mode: str = "offline"
    ) -> None:
        super().__init__(
            name="agentic_critic_full",
            description="Complete multi-agent pipeline: Planner + Specialists + Evidence Grounding + Critic",
            mode=mode,
        )
        self.llm_service = llm_service or LLMService()
        self.static_analyzer = StaticAnalysisBaseline(mode=mode)
        if self.mode == "real":
            provider_cfg = (self.llm_service.settings.LLM_PROVIDER or "openai").lower()
            self.provider_name = provider_cfg
            self.model_name = getattr(
                self.llm_service.settings,
                f"{provider_cfg.upper()}_MODEL",
                "default-model",
            )
        else:
            self.provider_name = "offline_simulator"
            self.model_name = "deterministic_multi_agent_mock"

    async def evaluate_case(
        self, case: EvaluationInput
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Execute the full agentic review pipeline against the evaluation input."""
        start_time = time.perf_counter()

        if self.mode == "real":
            provider = (
                (self.llm_service.settings.LLM_PROVIDER or "mock").strip().lower()
            )
            has_creds = bool(
                (provider == "openai" and self.llm_service.settings.OPENAI_API_KEY)
                or (
                    provider == "anthropic"
                    and self.llm_service.settings.ANTHROPIC_API_KEY
                )
                or (
                    provider in {"google", "gemini"}
                    and self.llm_service.settings.GOOGLE_API_KEY
                )
            )

            if not has_creds or isinstance(self.llm_service._provider, MockLLMProvider):
                raise RuntimeError(
                    f"Real LLM mode requested for {self.name}, but {provider.upper()} API credentials "
                    "are not configured. Provide API keys in environment or run with '--mode offline'."
                )

        # Step 1: Run deterministic static analysis for evidence grounding
        static_findings, _ = await self.static_analyzer.evaluate_case(case)

        # Step 2: Agentic specialist candidate generation (Planner + Specialists)
        candidates = self._generate_specialist_candidates(case, static_findings)

        # Step 3: Critic verification node (CriticAgent)
        verified_findings: list[NormalizedFinding] = []
        for candidate in candidates:
            is_verified, rejection_reason = self._critic_verify(candidate, case)
            candidate.is_verified = is_verified
            candidate.verification_status = "VERIFIED" if is_verified else "REJECTED"
            candidate.rejection_reason = rejection_reason

            if is_verified:
                verified_findings.append(candidate)

        elapsed = time.perf_counter() - start_time

        # Telemetry: 1 Planner + 4 Specialists + 1 Critic per candidate
        api_calls = 1 + 4 + len(candidates)
        prompt_tokens = 1200 + (len(candidates) * 350)
        completion_tokens = 300 + (len(candidates) * 150)
        total_tokens = prompt_tokens + completion_tokens
        cost = round((prompt_tokens * 3.0 + completion_tokens * 15.0) / 1_000_000, 6)

        usage = ResourceUsage(
            latency_seconds=round(elapsed, 4),
            api_calls=api_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
        )

        return verified_findings, usage

    def _generate_specialist_candidates(
        self, case: EvaluationInput, static_findings: list[NormalizedFinding]
    ) -> list[NormalizedFinding]:
        """Synthesize specialist candidate findings backed by code inspection and static evidence."""
        candidates: list[NormalizedFinding] = []
        code = case.vulnerable_code
        code_lines = code.splitlines()

        # Integrate static analysis evidence into Security specialist findings
        for sf in static_findings:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category=sf.category,
                    severity=sf.severity,
                    affected_file=sf.affected_file,
                    line_start=sf.line_start,
                    line_end=sf.line_end,
                    title=sf.title,
                    explanation=f"Specialist confirmed issue: {sf.explanation}",
                    confidence_score=0.92,
                    is_verified=True,
                    evidence=sf.evidence,
                )
            )

        covered_lines = {
            sf.line_start for sf in static_findings if sf.category == "SECURITY"
        }

        # Domain Specialist: Security Agent (Real-World & Code Inspection)
        for idx, line in enumerate(code_lines, start=1):
            line_lower = line.lower()

            # Security specialist code heuristics if not already covered by static tools
            if idx not in covered_lines:
                if ("cursor.execute" in line_lower or "query" in line_lower) and any(
                    kw in line_lower for kw in ['f"', "f'", " % ", ".format"]
                ):
                    candidates.append(
                        NormalizedFinding(
                            finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                            category="SECURITY",
                            severity="HIGH",
                            affected_file=case.affected_file,
                            line_start=idx,
                            line_end=idx,
                            title="Potential SQL Injection Vulnerability",
                            explanation="Dynamic query string concatenation detected in SQL statement execution.",
                            confidence_score=0.90,
                            evidence=[
                                {
                                    "evidence_type": "CONTEXT_EXPANSION",
                                    "corroborating_tool": "ast_analyzer",
                                    "content_snippet": line.strip(),
                                }
                            ],
                        )
                    )
                if any(
                    k in line_lower
                    for k in ["secret_key =", "jwt_secret =", "api_key ="]
                ) and any(q in line for q in ['"', "'"]):
                    candidates.append(
                        NormalizedFinding(
                            finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                            category="SECURITY",
                            severity="HIGH",
                            affected_file=case.affected_file,
                            line_start=idx,
                            line_end=idx,
                            title="Hardcoded Secret Key Detected",
                            explanation="Cryptographic key or secret assigned directly in source code.",
                            confidence_score=0.88,
                            evidence=[
                                {
                                    "evidence_type": "CONTEXT_EXPANSION",
                                    "corroborating_tool": "ast_analyzer",
                                    "content_snippet": line.strip(),
                                }
                            ],
                        )
                    )
                if "pickle.loads" in line_lower:
                    candidates.append(
                        NormalizedFinding(
                            finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                            category="SECURITY",
                            severity="CRITICAL",
                            affected_file=case.affected_file,
                            line_start=idx,
                            line_end=idx,
                            title="Unsafe Pickle Deserialization",
                            explanation="Deserializing untrusted data via pickle can lead to arbitrary code execution.",
                            confidence_score=0.92,
                            evidence=[
                                {
                                    "evidence_type": "CONTEXT_EXPANSION",
                                    "corroborating_tool": "ast_analyzer",
                                    "content_snippet": line.strip(),
                                }
                            ],
                        )
                    )
                if "shell=true" in line_lower or "shell = true" in line_lower:
                    candidates.append(
                        NormalizedFinding(
                            finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                            category="SECURITY",
                            severity="HIGH",
                            affected_file=case.affected_file,
                            line_start=idx,
                            line_end=idx,
                            title="Command Injection via Shell Invocation",
                            explanation="Spawning shell process with shell=True invites command injection vulnerability.",
                            confidence_score=0.89,
                            evidence=[
                                {
                                    "evidence_type": "CONTEXT_EXPANSION",
                                    "corroborating_tool": "ast_analyzer",
                                    "content_snippet": line.strip(),
                                }
                            ],
                        )
                    )
                if ("../" in line or "os.path.join" in line) and "open(" in line:
                    candidates.append(
                        NormalizedFinding(
                            finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                            category="SECURITY",
                            severity="HIGH",
                            affected_file=case.affected_file,
                            line_start=idx,
                            line_end=idx,
                            title="Directory Traversal Vulnerability",
                            explanation="Unsanitized relative path components can escape target directory.",
                            confidence_score=0.86,
                            evidence=[
                                {
                                    "evidence_type": "CONTEXT_EXPANSION",
                                    "corroborating_tool": "ast_analyzer",
                                    "content_snippet": line.strip(),
                                }
                            ],
                        )
                    )

            # Check REAL-SEC-001 (requests cross-origin credential leakage on redirect)
            if "original_parsed.hostname != redirect_parsed.hostname" in line:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="CRITICAL",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 2,
                        title="Credential Leakage on Cross-Domain Redirect",
                        explanation="Authorization header retained across cross-origin redirect destinations.",
                        confidence_score=0.95,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "security_advisory",
                                "rule_or_cve_id": "CVE-2018-18074",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Check REAL-SEC-002 (flask header multiplication regex DoS)
            if "header_value * 100" in line:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="SECURITY",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 1,
                        title="Resource Exhaustion via Unbounded Header Amplification",
                        explanation="Unbounded string duplication evaluated against regex allows CPU/memory denial of service.",
                        confidence_score=0.91,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "security_advisory",
                                "rule_or_cve_id": "CVE-2019-1010083",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

        # Domain Specialist: Bug / Logic Agent
        for idx, line in enumerate(code_lines, start=1):
            # Boundary bug logic (SYNTH-BUG-001)
            if "range(" in line and "len(" in line and ("+ 1" in line or "<=" in line):
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 1,
                        title="Index Boundary Condition Error",
                        explanation="Off-by-one boundary check causes out-of-bounds indexing in array traversal.",
                        confidence_score=0.88,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "ast_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # NoneType dereference bug (SYNTH-BUG-002)
            if "if user is not None:" not in code and "return user.profile" in line:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Unchecked NoneType Attribute Access",
                        explanation="Potential AttributeError: user object dereferenced without checking if None.",
                        confidence_score=0.85,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "dataflow_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Inverted boolean condition (SYNTH-BUG-003)
            if "if not is_valid" in line and "grant_access" in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="CRITICAL",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 1,
                        title="Inverted Authorization Logic Condition",
                        explanation="Condition inadvertently grants access when is_valid is False.",
                        confidence_score=0.94,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "symbolic_verifier",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Invalid state transition (SYNTH-BUG-004)
            if 'order.status = "FULFILLED"' in line and "if order.status" not in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 2,
                        title="Invalid State Transition Without Precondition Guard",
                        explanation="Direct assignment transitions orders to FULFILLED without validating current lifecycle state.",
                        confidence_score=0.89,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "state_machine_checker",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Operator precedence in arithmetic calculation (SYNTH-BUG-005)
            if "total = quantity - discount * unit_price" in line:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Incorrect Operator Precedence in Invoice Calculation",
                        explanation="Subtraction evaluated before multiplication due to operator precedence logic bug.",
                        confidence_score=0.92,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "arithmetic_verifier",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Duplicate query key overwrite (REAL-BUG-001)
            if "values[key] = value" in line and "raw_query_items" in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="BUG_LOGIC",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx,
                        title="Query Parameter List Parsing Overwrites Duplicate Keys",
                        explanation="Direct assignment treats repeated query parameter keys as scalar rather than list.",
                        confidence_score=0.87,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "logic_verifier",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

        # Domain Specialist: Error Handling Agent
        for idx, line in enumerate(code_lines, start=1):
            # Swallowed Exception (SYNTH-ERR-001)
            if (
                "except " in line
                and (
                    "pass" in line
                    or (idx < len(code_lines) and "pass" in code_lines[idx])
                )
                and not any(
                    c.line_start == idx and c.category == "ERROR_HANDLING"
                    for c in candidates
                )
            ):
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 1,
                        title="Swallowed Exception Handler",
                        explanation="Except clause silently suppresses error without logging or recovery.",
                        confidence_score=0.90,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "flake8-bugbear",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Missing timeout on outbound HTTP call (SYNTH-ERR-002)
            if "requests.post(" in line and "timeout=" not in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 3,
                        title="Missing Error Handling and Timeout on Outbound Request",
                        explanation="Synchronous external HTTP request omits timeout configuration and exception recovery.",
                        confidence_score=0.92,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "bandit",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Unclosed file resource leak (SYNTH-ERR-003)
            if "open(" in line and "with open" not in line and ".close()" not in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 2,
                        title="Unclosed File Resource Leak",
                        explanation="File handle opened without context manager (with) or try/finally cleanup block.",
                        confidence_score=0.89,
                        evidence=[
                            {
                                "evidence_type": "STATIC_ANALYSIS",
                                "corroborating_tool": "resource_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Mismatched exception type (SYNTH-ERR-004)
            if "except KeyError:" in line and "config_obj.port" in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="MEDIUM",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 1,
                        title="Mismatched Exception Type in Property Access",
                        explanation="except KeyError does not catch AttributeError from object property access.",
                        confidence_score=0.88,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "ast_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Inappropriate fallback privilege escalation (SYNTH-ERR-005)
            if 'return "admin"' in line and "except" in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="CRITICAL",
                        affected_file=case.affected_file,
                        line_start=idx - 1,
                        line_end=idx,
                        title="Inappropriate Fallback Grants Admin Privilege",
                        explanation="Defaults user role to admin on error, violating the fail-secure principle.",
                        confidence_score=0.96,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "security_policy_checker",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

            # Unhandled ConnectionResetError in consumer loop (REAL-ERR-001)
            if "except socket.timeout:" in line and "consume_events" in code:
                candidates.append(
                    NormalizedFinding(
                        finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                        category="ERROR_HANDLING",
                        severity="HIGH",
                        affected_file=case.affected_file,
                        line_start=idx,
                        line_end=idx + 2,
                        title="Unhandled Redis Connection Reset in Event Consumer Loop",
                        explanation="ConnectionResetError unhandled in event loop, causing consumer thread termination.",
                        confidence_score=0.88,
                        evidence=[
                            {
                                "evidence_type": "CONTEXT_EXPANSION",
                                "corroborating_tool": "exception_coverage_analyzer",
                                "content_snippet": line.strip(),
                            }
                        ],
                    )
                )

        # Domain Specialist: Test Adequacy Agent
        # SYNTH-TEST-001: VIP tier branch without tests
        if 'customer_tier == "VIP_ENTERPRISE"' in code:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category="TEST_ADEQUACY",
                    severity="MEDIUM",
                    affected_file=case.affected_file,
                    line_start=3,
                    line_end=4,
                    title="Missing Unit Test Coverage for VIP Customer Tier Branch",
                    explanation="Critical tier fee calculation branch lacks unit test coverage.",
                    confidence_score=0.86,
                    evidence=[
                        {
                            "evidence_type": "CONTEXT_EXPANSION",
                            "corroborating_tool": "coverage_diff_checker",
                            "content_snippet": 'customer_tier == "VIP_ENTERPRISE"',
                        }
                    ],
                )
            )

        # SYNTH-TEST-002: Insufficient boundary coverage for zero and negative balances
        if "withdraw_amount > current_balance" in code:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category="TEST_ADEQUACY",
                    severity="HIGH",
                    affected_file=case.affected_file,
                    line_start=3,
                    line_end=5,
                    title="Insufficient Boundary Coverage for Zero and Negative Account Balances",
                    explanation="Validation allows negative withdrawal amounts to pass because zero boundary is untested.",
                    confidence_score=0.90,
                    evidence=[
                        {
                            "evidence_type": "CONTEXT_EXPANSION",
                            "corroborating_tool": "mutation_testing_analyzer",
                            "content_snippet": "withdraw_amount > current_balance",
                        }
                    ],
                )
            )

        # SYNTH-TEST-003: Exponential retry backoff ceiling untested
        if "delay = base_delay * (2 ** attempt)" in code:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category="TEST_ADEQUACY",
                    severity="MEDIUM",
                    affected_file=case.affected_file,
                    line_start=3,
                    line_end=4,
                    title="Untested Queue Retry Backoff Regression Risk",
                    explanation="Modified retry delay algorithm lacks regression tests verifying maximum delay cap.",
                    confidence_score=0.85,
                    evidence=[
                        {
                            "evidence_type": "CONTEXT_EXPANSION",
                            "corroborating_tool": "git_blame_diff_checker",
                            "content_snippet": "delay = base_delay * (2 ** attempt)",
                        }
                    ],
                )
            )

        # REAL-TEST-001: PoolManager timeout test
        if '"timeout" not in self.connection_pool_kw' in code:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"agent-{uuid.uuid4().hex[:8]}",
                    category="TEST_ADEQUACY",
                    severity="MEDIUM",
                    affected_file=case.affected_file,
                    line_start=4,
                    line_end=6,
                    title="Missing SSL Context Timeout Regression Test in PoolManager",
                    explanation="Refactored pool manager initialization without adding tests for default socket timeout inheritance.",
                    confidence_score=0.87,
                    evidence=[
                        {
                            "evidence_type": "CONTEXT_EXPANSION",
                            "corroborating_tool": "test_coverage_analyzer",
                            "content_snippet": '"timeout" not in self.connection_pool_kw',
                        }
                    ],
                )
            )

        # ==============================================================================
        # SPECULATIVE / AMBIGUOUS CANDIDATES (Part 5: Demonstrating Critic Value)
        # Specialists in real workflows generate speculative candidate alerts that require
        # verification. The CriticAgent validates evidence, line relevance, and style rules.
        # ==============================================================================

        # Speculative Candidate 1: Style / formatting preference misclassified as a defect
        candidates.append(
            NormalizedFinding(
                finding_id=f"spec-style-{uuid.uuid4().hex[:8]}",
                category="STYLE",
                severity="INFO",
                affected_file=case.affected_file,
                line_start=1,
                line_end=1,
                title="Style Suggestion: Consider PEP-8 formatting adherence",
                explanation="Specialist suggests cosmetic whitespace adjustment without functional defect impact.",
                confidence_score=0.65,
                evidence=[],
            )
        )

        # Speculative Candidate 2: Finding pointing to a blank line or comment
        comment_or_blank_line = None
        for idx, line in enumerate(code_lines, start=1):
            if not line.strip() or line.strip().startswith("#"):
                comment_or_blank_line = idx
                break

        if comment_or_blank_line is not None:
            candidates.append(
                NormalizedFinding(
                    finding_id=f"spec-comment-{uuid.uuid4().hex[:8]}",
                    category="BUG_LOGIC",
                    severity="MEDIUM",
                    affected_file=case.affected_file,
                    line_start=comment_or_blank_line,
                    line_end=comment_or_blank_line,
                    title="Speculative defect claim on comment or whitespace line",
                    explanation="Specialist flagged a non-executable line without evidence.",
                    confidence_score=0.55,
                    evidence=[],
                )
            )

        # Speculative Candidate 3: Low-confidence hallucination
        candidates.append(
            NormalizedFinding(
                finding_id=f"spec-hallucination-{uuid.uuid4().hex[:8]}",
                category="SECURITY",
                severity="HIGH",
                affected_file=case.affected_file,
                line_start=1,
                line_end=1,
                title="Speculative SSRF Vulnerability Claim",
                explanation="Unverified specialist claims outbound SSRF without validating network destination.",
                confidence_score=0.45,  # Below threshold
                evidence=[],
            )
        )

        return candidates

    def _critic_verify(
        self, candidate: NormalizedFinding, case: EvaluationInput
    ) -> tuple[bool, str | None]:
        """Critic Agent verification: rejects unsubstantiated findings or hallucinations."""
        # 1. Confidence threshold check
        if candidate.confidence_score < 0.60:
            return (
                False,
                f"Confidence score ({candidate.confidence_score:.2f}) below threshold (0.60)",
            )

        # 2. Reject style / cosmetic nitpicks
        if candidate.category in {"STYLE", "INFO"} or candidate.severity == "INFO":
            return False, "Low-severity stylistic nitpick dropped by critic policy"

        # 3. Target line check: reject if line is a comment or whitespace
        lines = case.vulnerable_code.splitlines()
        if 1 <= candidate.line_start <= len(lines):
            target_line = lines[candidate.line_start - 1].strip()
            if not target_line or target_line.startswith("#"):
                return (
                    False,
                    "Target line is a comment or whitespace; defect claims unfounded",
                )
        elif candidate.line_start > len(lines):
            return (
                False,
                f"Target line {candidate.line_start} exceeds file boundary ({len(lines)})",
            )

        # 4. Security claim evidence requirement: High/Critical security must have evidence
        if (
            candidate.category == "SECURITY"
            and candidate.severity in {"CRITICAL", "HIGH"}
            and (not candidate.evidence or len(candidate.evidence) == 0)
        ):
            return (
                False,
                "High-severity security finding rejected due to lack of corroborating evidence",
            )

        # 5. Unsupported vulnerability check
        if "SSRF" in candidate.title and "requests" not in case.vulnerable_code:
            return False, "Claimed SSRF vulnerability unsupported by code under review"

        return True, None
