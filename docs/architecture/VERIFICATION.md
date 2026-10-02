# Verification Agent & Evidence Grounding Engine Architecture (Phase 4)

## 1. Overview & Research Objective

Phase 4 introduces the verification layer for the research project:
**"An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review"**

Specialist domain agents (Security, BugLogic, ErrorHandling, TestAdequacy) in Phase 3.2 produce **candidate findings** marked with:
- `verification_status = UNVERIFIED`
- `confidence_score = 0.0`

The central hypothesis of this project is that automated code reviews cannot be trusted if agents publish candidate findings directly. Unverified LLM outputs frequently exhibit:
1. Hallucinated code references and non-existent functions.
2. Citations of unmodified lines outside the pull request diff.
3. Speculative security vulnerabilities contradicted by language runtime semantics or surrounding framework guards.
4. Generic style or best-practice claims lacking concrete code evidence.

Phase 4 implements a dedicated **Critic / Verification Agent** and a modular **Evidence Grounding Engine** that deterministically tests and semantically verifies every candidate finding against repository ground truth before any downstream persistence or GitHub publication.

```
+-------------------------------------------------------------------------+
|                          SPECIALIST ENSEMBLE                            |
|     SecurityAgent  •  BugLogicAgent  •  ErrorHandling  •  TestAdequacy  |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
                          [ Candidate Findings ]
                     (UNVERIFIED, raw_confidence)
                                     │
                                     ▼
+-------------------------------------------------------------------------+
|                        PHASE 4: VERIFICATION LAYER                      |
|                                                                         |
|  1. DETERMINISTIC EVIDENCE GATES (Pre-LLM)                              |
|     • File existence in PR diff                                         |
|     • Line coordinate validation & hunk boundaries                      |
|     • Commit SHA alignment                                              |
|     • Corroborating static analysis tool matching                       |
|                                                                         |
|  2. CRITIC AGENT (Semantic LLM Verification)                            |
|     • Distinguish facts from inferences                                 |
|     • Detect repo context contradictions                                |
|     • Calibrate independent confidence score                            |
|                                                                         |
|  3. EVIDENCE GROUNDING SERVICE (Synthesis)                              |
|     • Calibrate confidence (bonuses & penalties)                        |
|     • Enforce conservative verification threshold (>= 0.70)             |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
                    [ Verified / Rejected Findings ]
                  (VERIFIED or REJECTED with notes)
                                     │
                                     ▼
+-------------------------------------------------------------------------+
|                  FINDING PERSISTENCE (PostgreSQL)                       |
|              Transactional storage of verified/rejected                 |
+-------------------------------------------------------------------------+
                                     │
                                     ▼ (Future Phase 5)
                            [ GitHub Publisher ]
```

---

## 2. Evidence Grounding Engine Architecture

Verification logic is encapsulated within reusable services in `backend/app/services/evidence/` rather than monolithic agent code:

### 2.1 Component Structure
- [`DiffEvidenceResolver`](file:///d:/Projects/agentic-code-reviewer/backend/app/services/evidence/diff_resolver.py):
  - Resolves target files within the unified git diff.
  - Verifies whether cited line numbers fall inside modified, added, or deleted hunks.
  - Extracts targeted code excerpts (`context_window=3`) with line numbers and hunk headers.
- [`StaticEvidenceMatcher`](file:///d:/Projects/agentic-code-reviewer/backend/app/services/evidence/static_matcher.py):
  - Correlates candidate findings with deterministic evidence produced by Semgrep, Bandit, and pip-audit.
  - Supports direct matching (exact file, rule ID, and overlapping line range) and proximate matching (same file within `line_proximity_window=5` lines).
- [`FindingEvidenceValidator`](file:///d:/Projects/agentic-code-reviewer/backend/app/services/evidence/validator.py):
  - Executes fast, deterministic validation checks without consuming LLM tokens.
  - Produces detailed, structured rejection reasons when candidate findings violate structural invariants.
- [`EvidenceGroundingService`](file:///d:/Projects/agentic-code-reviewer/backend/app/services/evidence/grounding_service.py):
  - Coordinates verification context preparation.
  - Synthesizes the final `VerificationResult` from deterministic and LLM signals.
  - Calibrates explainable confidence scores.
  - Applies verification outcomes in-place to canonical `ReviewFinding` models.

---

## 3. Deterministic Verification First

To minimize token usage and eliminate obvious hallucinations immediately, candidate findings undergo deterministic validation before any LLM prompt is assembled:

| Gate | Validation Rule | Action on Failure |
| :--- | :--- | :--- |
| **File Existence** | `finding.affected_file` must exist in `changed_files` or `parsed_diff.files` | Deterministic REJECT (`"Cited file ... does not exist in PR diff"`) |
| **Line Validity** | `finding.line_number` must be a positive integer (`>= 1`) | Deterministic REJECT (`"Invalid cited line number ..."`) |
| **Diff Relevance** | Cited line must fall within the PR diff | Deterministic REJECT (`"Cited line ... is not within the PR diff"`) |
| **Commit Alignment** | Finding commit context must match the review run's target commit SHA | Deterministic REJECT (`"Commit SHA mismatch ..."`) |
| **Finding Integrity** | Title and explanation must be non-empty and well-formed | Deterministic REJECT (`"Malformed candidate finding ..."`) |

When any deterministic gate fails, the finding is assigned `VerificationStatus.REJECTED` and `confidence_score = 0.0` immediately, completely bypassing the Critic LLM call.

---

## 4. Evidence Hierarchy

Evidence evaluated during verification adheres to a strict confidence hierarchy:

1. **Exact Changed-Code Evidence:** Lines added (`+`) or modified within the PR diff hunks.
2. **Exact Diff Hunk Context:** Context lines (` `) immediately surrounding changes in the PR diff.
3. **Static Analysis Evidence:** Machine-verified alerts from Semgrep, Bandit, or pip-audit with concrete rule IDs and line coordinates.
4. **Relevant Repository Context:** Surrounding imports, class definitions, function signatures, and configuration files.
5. **Tests & Test Execution Evidence:** Existing unit/integration test definitions and fixtures.
6. **Agent Reasoning & Heuristics:** Natural language inferences (treated as claims, not evidence).

> [!IMPORTANT]
> Generic style advice or ungrounded best-practice claims are categorized as speculative and are rejected under the conservative verification policy.

---

## 5. Critic Agent Architecture

The [`CriticAgent`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/critic.py) implements the semantic verification layer:

### 5.1 Inputs and Prompting
The Critic receives a tightly bounded, sanitized context (`VerificationContext`) containing:
- Repository metadata, PR number, commit SHA.
- Candidate finding title, severity, explanation, and originating specialist agent.
- Target file path, line coordinate, and diff hunk excerpt.
- Corroborating static analysis findings with rule IDs and tool provenance.
- Bounded repository context.

### 5.2 System Prompt (`CRITIC_SYSTEM_PROMPT` v1.0.0)
Defined in [`backend/app/agents/critic_prompt.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/critic_prompt.py), the prompt instructs the Critic to:
1. Act exclusively as an impartial code review verifier.
2. Never invent code, rules, or test outputs.
3. Explicitly distinguish factual defects from speculative concerns.
4. Detect contradictions (e.g., claiming SQL injection on an ORM query, or null pointer exception on a type-guarded variable).
5. Produce strictly structured JSON conforming to `CriticStructuredOutput`.

### 5.3 Structured Output Model
```python
class CriticStructuredOutput(BaseModel):
    decision: str  # "VERIFIED" or "REJECTED"
    calibrated_confidence: float  # 0.0 to 1.0
    evidence_sufficiency: bool
    contradiction_detected: bool
    critic_notes: str
    verification_reasons: list[str]
    rejection_reasons: list[str]
```

---

## 6. Confidence Calibration

Confidence scores are never copied blindly from specialist agents. The `EvidenceGroundingService` independently calculates the calibrated confidence using an explainable, deterministic scoring model:

$$\text{Score} = \text{CriticScore} + \Delta_{\text{changed\_line}} + \Delta_{\text{static\_tool}} - \Delta_{\text{contradiction}} - \Delta_{\text{out\_of\_diff}}$$

Where:
- $\Delta_{\text{changed\_line}} = +0.05$ if cited line is an added line in the diff hunk.
- $\Delta_{\text{static\_tool}} = +0.10$ if corroborated by an independent static analysis tool.
- $\Delta_{\text{contradiction}} = -0.50$ if repository context contradicts the defect claim.
- $\Delta_{\text{out\_of\_diff}} = -0.40$ if line is outside the PR diff.
- If `evidence_sufficiency = False`, confidence is capped at $\le 0.45$.

### Conservative Verification Threshold
To achieve `VerificationStatus.VERIFIED`:
1. Decision must be `VERIFIED`.
2. `evidence_sufficiency` must be `True`.
3. `contradiction_detected` must be `False`.
4. `line_in_diff` must be `True`.
5. Calibrated confidence score must be $\ge 0.70$.

Findings failing any of these criteria are marked `VerificationStatus.REJECTED`.

---

## 7. LangGraph Verification Topology

The review workflow graph is extended to support parallel verification:

```
[prepare_review_context]
          │
          ▼
      [planner]
          │
          ▼ (Conditional Fan-Out: ReviewPlan.active_agents)
  ├──► [security_agent]       ──┐
  ├──► [bug_logic_agent]      ──┼──► [aggregate_findings]
  ├──► [error_handling_agent] ──┤              │
  └──► [test_adequacy_agent]  ──┘              │
                                               ▼ (_route_verification)
                     ┌─────────────────────────┴────────────────────────┐
                     │ (Candidates > 0)                                 │ (Candidates == 0)
                     ▼                                                  ▼
     [verify_candidate_finding (Send 1)]                                │
     [verify_candidate_finding (Send 2)] ──┐                            │
     [verify_candidate_finding (Send N)] ──┼──► [aggregate_verification]◄┘
                                           │              │
                                           ▼              ▼
                                                      [   END   ]
```

### 7.1 LangGraph `Send` API Dynamic Fan-Out
- In `_route_verification`, each candidate finding is dispatched via LangGraph's dynamic `Send("verify_candidate_finding", payload)` primitive.
- Findings are verified concurrently and independently.
- If zero candidate findings are generated by specialists, the router returns `["aggregate_verification"]`, skipping Critic invocation cleanly and transitioning to `END`.

### 7.2 Reducers and State Merging
`ReviewState` incorporates dedicated verification channels utilizing the `merge_verification_results` reducer:
- `verified_findings`: List of `ReviewFinding` models marked `VERIFIED`.
- `rejected_findings`: List of `ReviewFinding` models marked `REJECTED`.
- `verification_results`: Full audit trail of `VerificationResult` instances.
- `verification_errors`: Non-fatal errors encountered during per-finding verification.

---

## 8. Failure Isolation & Resiliency

Per-finding verification is fully isolated:
- If verification of Finding 1 succeeds, Finding 2 experiences a transient LLM timeout, and Finding 3 is rejected deterministically:
  - Finding 1 is added to `verified_findings`.
  - Finding 3 is added to `rejected_findings`.
  - The timeout for Finding 2 is logged in `verification_errors`.
  - The overall workflow completes with `status = "COMPLETED"`.
- Review-level failure occurs only if core graph infrastructure (context preparation, planning) encounters unrecoverable system failures.

---

## 9. Persistence & Database Boundary

Findings are persisted to PostgreSQL via [`FindingPersistenceService`](file:///d:/Projects/agentic-code-reviewer/backend/app/services/finding_persistence_service.py):
- Operates on verified review runs, validating `ReviewRun.commit_sha == expected_commit_sha`.
- Persists both `VERIFIED` and `REJECTED` findings with complete evidence linkages, critic notes, and rejection reasons.
- **Zero Database Migrations:** The existing database schema (`findings` table) already contains `verification_status: String(50)`, `confidence_score: Float`, `critic_notes: Text`, and `rejection_reason: Text`.
- **Zero GitHub Publication:** Strictly enforced boundary. No PR comments, review submissions, or Check Runs are created during this phase.

---

## 10. Research & Evaluation Metrics (Phase 7 Foundation)

Phase 4 captures structured verification metadata to enable empirical evaluation in Phase 7:
- **False-Positive Reduction Rate:** $\frac{N_{\text{rejected}}}{N_{\text{candidate}}}$
- **Evidence Corroboration Rate:** Percentage of candidate findings backed by static analysis tools.
- **Confidence Calibration Delta:** Shift between specialist `raw_confidence` and Critic `confidence_score`.
- **Deterministic Filter Efficiency:** Percentage of invalid findings caught pre-LLM.
- **Verification Latency:** Mean execution time per verified finding.
