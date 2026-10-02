# Domain Specialist Agents Architecture (Phase 3.2)

## 1. Overview & Architectural Role

Phase 3.2 extends the LangGraph review workflow established in Phase 3.1 with an ensemble of four specialized domain agents:
1. **SecurityAgent**: Identifies application security vulnerabilities, injection risks, authentication/authorization flaws, and hardcoded secrets.
2. **BugLogicAgent**: Detects logical bugs, off-by-one errors, state machine violations, broken control flows, and regressions.
3. **ErrorHandlingAgent**: Analyzes unhandled exceptions, swallowed errors, resource leaks, failure-path recovery, and retry behavior.
4. **TestAdequacyAgent**: Evaluates test coverage gaps, missing negative/edge-case tests, untested API modifications, and test suite regressions.

These agents operate concurrently down-stream of the **Planner Agent**, analyzing the changed code and deterministic evidence under the guidance of the generated `ReviewPlan`.

```
START
  │
  ▼
[prepare_review_context]
  │
  ▼
[planner] (PlannerAgent produces canonical ReviewPlan)
  │
  ▼ (Conditional Fan-Out: ReviewPlan.active_agents)
  ├──► [security_agent]       ──┐
  ├──► [bug_logic_agent]      ──┼──► [aggregate_findings] ──► END
  ├──► [error_handling_agent] ──┤
  └──► [test_adequacy_agent]  ──┘
```

> [!IMPORTANT]
> **Strict Verification Boundary:**
> Specialist agents produce **candidate findings** only (`VerificationStatus.UNVERIFIED`, `confidence_score = 0.0`).
> Specialist agents are strictly forbidden from publishing directly to GitHub, modifying PR review state, or marking findings as verified. All candidate findings must pass through the downstream Critic / Verification layer (Phase 4).

---

## 2. Common Specialist Agent Abstraction

All specialist agents inherit from a unified base class defined in [`backend/app/agents/base.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/base.py):

### 2.1 Base Class: `BaseSpecialistAgent`
```python
class BaseSpecialistAgent(abc.ABC):
    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm_service: LLMService | None = None,
        default_issue_type: IssueType = IssueType.OTHER,
    ) -> None: ...
```

Key responsibilities of `BaseSpecialistAgent`:
1. **Context Extraction & Bounding**: Transforms the workflow's `ReviewState` into a scoped, bounded `SpecialistContext`.
2. **Structured LLM Invocation**: Invokes `LLMService.generate_structured()` using Pydantic validation schema `SpecialistReviewOutput`.
3. **Evidence Grounding & Normalization**: Automatically enriches candidate findings with:
   - Agent provenance (`agent_name = self.name`)
   - Verification status (`verification_status = UNVERIFIED`)
   - Uncalibrated confidence (`confidence_score = 0.0`)
   - Commit SHA and PR identifier propagation
   - Diff hunk and static analysis evidence linkage
4. **Failure Isolation**: Provides an `execute_node()` entry point for LangGraph nodes that catches exceptions, classifies them into `WorkflowErrorCategory`, marks retryability, and records failures in `specialist_errors` without terminating peer agents.

### 2.2 Input Contract: `SpecialistContext`
Specialist agents receive only the bounded context required for their domain:
- `review_run_id`: Workflow execution ID
- `repository_full_name`: Repository identifier (e.g. `owner/repo`)
- `commit_sha` & `base_sha`: Exact commit SHAs under review
- `pr_title` & `pr_author`: PR metadata
- `review_scope`: Planner review scope (`FULL`, `SELECTIVE`, `MINIMAL`, `TRIVIAL`)
- `focus_areas`: Domain-specific focus directives from the Planner
- `target_files`: Filtered list of files assigned to this specialist
- `diff_context`: Bounded git diff hunks filtered to target files
- `evidence_items`: Relevant normalized `EvidenceModel` items (e.g., Semgrep, Bandit, pip-audit findings)
- `file_chunks`: Chunking metadata if large PR triage was activated

### 2.3 Output Contract: `SpecialistReviewOutput`
LLM structured output is validated against:
```python
class SpecialistReviewOutput(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    analysis_summary: str = Field(default="")
    coverage_limitations: list[str] = Field(default_factory=list)
```

---

## 3. Domain Specialist Ensembles

### 3.1 `SecurityAgent`
- **File**: [`backend/app/agents/security.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/security.py)
- **Prompt**: [`backend/app/agents/security_prompt.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/security_prompt.py)
- **Domain Focus**:
  - OWASP Top 10 vulnerabilities (SQLi, command injection, SSRF, XSS, path traversal).
  - Broken access control, authorization bypass, insecure direct object references (IDOR).
  - Hardcoded secrets, API tokens, cryptographic weaknesses.
  - Insecure deserialization and unsafe file handling.
- **Evidence-First Rule**: Must correlate with static analysis evidence (`Semgrep`, `Bandit`, `pip-audit`). If static evidence exists for a file/line, the agent references it explicitly.

### 3.2 `BugLogicAgent`
- **File**: [`backend/app/agents/bug_logic.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/bug_logic.py)
- **Prompt**: [`backend/app/agents/bug_logic_prompt.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/bug_logic_prompt.py)
- **Domain Focus**:
  - Control flow anomalies, inverted conditionals, off-by-one errors.
  - State machine transitions, uninitialized states, race conditions.
  - Null/None dereferences, collection mutation during iteration.
  - Incorrect data transformations and business rule violations.
- **Grounding Rule**: Prohibited from inventing runtime behavior; must ground findings in the diff and visible repository context.

### 3.3 `ErrorHandlingAgent`
- **File**: [`backend/app/agents/error_handling.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/error_handling.py)
- **Prompt**: [`backend/app/agents/error_handling_prompt.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/error_handling_prompt.py)
- **Domain Focus**:
  - Bare `except:` clauses, swallowed exceptions, improper error suppression.
  - Failure-path bugs, missing cleanup in `finally:` or context managers.
  - External API call failures without timeouts or retry strategies.
  - Inconsistent error responses and unhandled database exceptions.

### 3.4 `TestAdequacyAgent`
- **File**: [`backend/app/agents/test_adequacy.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/test_adequacy.py)
- **Prompt**: [`backend/app/agents/test_adequacy_prompt.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/agents/test_adequacy_prompt.py)
- **Domain Focus**:
  - Missing unit/integration tests for modified business logic or new API endpoints.
  - Untested error paths, exception handling, and edge cases.
  - Tests that do not assert meaningful invariants (false-positive tests).
  - Explicit recognition of limitations when test files are not included in the PR diff.

---

## 4. LangGraph Fan-Out and Fan-In Topology

The review graph in [`backend/app/orchestration/review_graph.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/review_graph.py) implements conditional fan-out:

### 4.1 Routing: `_route_specialists`
1. Inspects `ReviewState["review_plan"]["active_agents"]`.
2. Validates agent names against `KNOWN_SPECIALIST_AGENTS`.
3. Returns a list of node names to execute in parallel:
   - If `active_agents = ["security_agent", "bug_logic_agent"]`, LangGraph schedules both nodes concurrently.
   - If `active_agents = []` (e.g. trivial documentation changes), routes directly to `["aggregate_findings"]`.
   - If state status is `FAILED`, routes to `[END]`.

### 4.2 State Reducers (Concurrency Safety)
To prevent race conditions and overwrites during parallel specialist execution, `ReviewState` fields use LangGraph reducer functions defined in [`backend/app/orchestration/state.py`](file:///d:/Projects/agentic-code-reviewer/backend/app/orchestration/state.py):
- `candidate_findings: Annotated[list[dict[str, Any]], merge_candidate_findings]`:
  - Deduplicates by `finding_id`.
  - Semantically deduplicates by `(affected_file, line_number, normalized_title)`.
- `specialist_errors: Annotated[list[dict[str, Any]], merge_specialist_errors]`:
  - Combines error records across concurrent agents.
- `error_messages: Annotated[list[str], merge_error_messages]`:
  - Merges human-readable error messages.

### 4.3 Aggregation: `_aggregate_findings_node`
The fan-in node collects outputs after all active specialists complete:
- Calculates candidate findings count and per-agent breakdown.
- Evaluates failure isolation:
  - If **some** specialists succeeded, status is set to `COMPLETED` and partial findings are preserved.
  - If **all** active specialists failed and zero findings were produced, marks status as `FAILED` with the first error category.

---

## 5. Candidate Finding Contract & Lifecycle

```
[Specialist Agent]
        │ Produces candidate finding (VerificationStatus.UNVERIFIED, confidence=0.0)
        ▼
[ReviewState.candidate_findings] (Deduplicated, enriched with provenance & evidence)
        │
        ▼
[Future Critic / Verification Agent] (Phase 4: validates evidence, filters false positives)
        │
        ▼
[Database Persistence] (Phase 4: maps to FindingModel in PostgreSQL)
        │
        ▼
[GitHub Publisher] (Phase 5: creates PR review comments with idempotency checks)
```

Each candidate finding uses the canonical [`ReviewFinding`](file:///d:/Projects/agentic-code-reviewer/backend/app/schemas/finding.py) schema:
- `finding_id`: Unique UUID
- `issue_type`: Category enum (`SECURITY`, `BUG_LOGIC`, `ERROR_HANDLING`, `TEST_ADEQUACY`)
- `severity`: Severity enum (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`)
- `affected_file` & `line_number`: Precise code coordinates
- `title` & `explanation`: Clear defect description
- `evidence`: Bounded list of `EvidenceModel` items
- `recommendation`: Concrete actionable remediation advice
- `agent_name`: Name of producing specialist agent
- `verification_status`: Strictly `UNVERIFIED`

---

## 6. Failure Isolation and Retry Classification

Specialist agent failures are classified consistently with the Phase 3.1 error hierarchy:

| Error Type | Category | Retryable | Behavior |
| :--- | :--- | :--- | :--- |
| `LLMTimeoutError` | `LLM_TIMEOUT` | **Yes** | Recorded in `specialist_errors`; peer agents proceed. |
| `LLMProviderError` (429/503) | `LLM_PROVIDER_ERROR` | **Yes** | Recorded in `specialist_errors`; peer agents proceed. |
| `InvalidSpecialistOutputError` | `INVALID_SPECIALIST_OUTPUT` | **No** | Pydantic validation failure recorded; peer agents proceed. |
| `SpecialistExecutionError` | `SPECIALIST_EXECUTION_FAILURE` | **No** | General exception caught and recorded. |

---

## 7. Security Boundaries

In accordance with Section 16 of the architecture:
1. **No Secret Ingestion**: Prompts sanitize environment variables, tokens, and credentials.
2. **Context Bounding**: PR diffs are bounded to prevent token window overflow.
3. **No External Calls / Code Execution**: Specialist agents cannot run shell commands or execute code.
4. **No Direct GitHub Mutation**: Specialist agents cannot call GitHub APIs.
5. **Deterministic Offline Testing**: Tests use `MockLLMProvider` with zero network access or external vendor dependencies.
